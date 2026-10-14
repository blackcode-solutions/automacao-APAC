from __future__ import annotations

from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, biodata_locators_pendentes, config_dir, resolve_path
from apac_bot.logging_safe import setup_logging
from apac_bot.models import PacienteDados
from apac_bot.normalize import sexo_para_apac, tem_cpf_valido
from apac_bot.secrets import SecretsError, load_biodata_credentials
from apac_bot.sheet import (
    opcao_contem_prontuario,
    prontuario_so_digitos,
    sanitizar_nome_opcao,
)

log = setup_logging()


class BiodataMappingError(Exception):
    """Consulta real bloqueada: localizadores incompletos."""


DEFAULT_LOGIN_LOCATORS = {
    "campo_usuario": "#inputUsuario",
    "campo_senha": "input[name='password']",
    "botao_entrar": "button[type='submit']",
    # /home (atendimento) ou /consultorio/... (consultório) — depende do usuário
    "indicador_logado": "text=Usuário:",
    "url_apos_login": ["**/home*", "**/consultorio/**"],
}

DEFAULT_REAUTH_LOCATORS = {
    "titulo": "Autenticação",
    "campo_senha": "input[type='password'], input[name='password']",
    "botao_login": "button:has-text('Login')",
}

DEFAULT_LOGOUT_LOCATORS = {
    "menu_usuario": "text=Usuário:",
    "botao_sair": "button:has-text('Sair')",
}


class BiodataConnector:
    """
    Conector Playwright para BIODATA.

    Fluxo mapeado:
    login (rota depende do usuário: /home, /consultorio/..., etc.)
    -> menu lateral Atendimento -> Pesquisar tela "cadastro de paciente"
    -> Cadastro de Pacientes -> Pesquisar -> Pesquisar Cliente (nome) -> Confirmar
    """

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._browser = None
        self._context = None
        self._page = None
        self._pw = None
        self._cadastro_aberto = False
        pendentes = biodata_locators_pendentes(cfg)
        if pendentes:
            raise BiodataMappingError(
                "Mapeamento BIODATA incompleto. Localizadores pendentes: "
                + ", ".join(pendentes)
                + ". Preencha biodata.navegacao / biodata.locators em config.json."
            )

    def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        biodata = self.cfg.biodata
        base = config_dir(self.cfg)
        user_data = resolve_path(
            base, Path(str(biodata.get("user_data_dir", "browser_profile")))
        )
        user_data.mkdir(parents=True, exist_ok=True)
        timeout = int(self.cfg.timeouts.get("biodata_ms", 15000))

        self._pw = sync_playwright().start()

        def _launch() -> None:
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data),
                headless=False,
                viewport={"width": 1400, "height": 900},
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(timeout)

        _launch()
        log.info("Abrindo BIODATA (perfil dedicado — cookies de sessao preservados).")
        locs = login_locators(self.cfg)
        pagina_ok = _escolher_pagina_ja_logada(self._context, locs)
        if pagina_ok is not None:
            self._page = pagina_ok
            self._page.set_default_timeout(timeout)
            log.info("Aba BIODATA ja autenticada — reutilizando.")
        try:
            _abrir_ou_reusar_sessao(self._page, self.cfg)
        except BiodataMappingError:
            # Nao apaga o perfil (destruiria a sessao de ~4h). Retry via /home.
            home = _url_home_biodata(self.cfg)
            if home:
                log.warning(
                    "Falha ao abrir sessao BIODATA — retry unico em /home "
                    "(perfil mantido)."
                )
                try:
                    self._page.goto(home, wait_until="domcontentloaded")
                    self._page.wait_for_timeout(1000)
                    _dismiss_blocking_overlays(self._page)
                except Exception as exc:
                    log.warning("Retry /home falhou: %s", exc)
                if _pagina_autenticada(self._page, locs) or _menu_lateral_visivel(
                    self._page
                ):
                    log.info("Sessão BIODATA recuperada no retry /home.")
                else:
                    raise
            else:
                raise
        self._abrir_cadastro_pacientes()

    def _nav(self) -> dict:
        return dict(self.cfg.biodata.get("navegacao") or {})

    def _loc(self) -> dict:
        return dict(self.cfg.biodata.get("locators") or {})

    def _abrir_cadastro_pacientes(self) -> None:
        assert self._page is not None
        page = self._page
        nav = self._nav()
        loc = self._loc()

        if page.get_by_text("Cadastro de Pacientes", exact=False).count() and page.get_by_role(
            "button", name="Pesquisar"
        ).count():
            # Já pode estar aberto
            self._tratar_reauth_se_necessario()
            self._cadastro_aberto = True
            return

        log.info("Abrindo menu Atendimento (na rota pós-login atual).")
        _dismiss_blocking_overlays(page)
        timeout_ms = int(self.cfg.timeouts.get("biodata_ms", 15000))
        # /consultorio pode demorar ou nao ter menu — retry + fallback /home
        _aguardar_menu_lateral(page, self.cfg, timeout_ms=timeout_ms)
        page.wait_for_timeout(800)
        modulo = page.locator(nav["modulo_atendimento"]).first
        if modulo.count() == 0:
            modulo = page.locator('#menuLateral [aria-label="Atendimento"] button').first
        modulo.click(timeout=15000)
        page.wait_for_selector(nav["campo_busca_menu"], state="visible")
        busca = page.locator(nav["campo_busca_menu"]).first
        busca.click()
        busca.fill("")
        busca.fill("cadastro de paciente")
        page.wait_for_timeout(800)
        item = page.locator(nav["item_cadastro_pacientes"]).first
        item.wait_for(state="visible")
        item.click()
        page.wait_for_timeout(1000)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        self._tratar_reauth_se_necessario()
        page.locator(loc["botao_pesquisar"]).last.wait_for(state="visible")
        self._cadastro_aberto = True
        log.info("Tela Cadastro de Pacientes aberta.")

    def _tratar_reauth_se_necessario(self) -> None:
        assert self._page is not None
        tratar_reauth_se_necessario(self._page, self.cfg)

    def _recuperar_sessao_e_cadastro(self) -> None:
        """
        Sessao provavelmente expirada (busca vazia): login completo em biodata.url
        e reabre Cadastro de Pacientes para nova tentativa de busca.
        """
        assert self._page is not None
        log.warning(
            "BIODATA: recuperando sessao (login completo) e reabrindo Cadastro."
        )
        ensure_biodata_login(self._page, self.cfg, force_full=True)
        self._cadastro_aberto = False
        self._abrir_cadastro_pacientes()

    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        """
        Busca no dialogo Pesquisar Cliente.
        Se campo_busca_id nao mapeado, usa campo_busca_nome (Tom Select aceita o ID).
        """
        return self.buscar_por_prontuario(id_paciente)

    def buscar_por_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        """Digita o prontuario/ID no dialogo (nao o nome) e abre o cadastro."""
        pront = prontuario_so_digitos(prontuario) or (prontuario or "").strip()
        if not pront:
            return None
        self._ensure_browser()
        assert self._page is not None
        loc = self._loc()
        campo_sel = loc.get("campo_busca_id") or loc.get("campo_busca_nome")
        if not campo_sel:
            log.warning("BIODATA: nenhum campo de busca configurado para prontuario.")
            return None

        log.info("BIODATA: buscando por prontuario=%s", pront)
        lista = self._buscar_lista_no_dialogo(
            termo=pront, campo_sel=campo_sel, prontuario_alvo=pront
        )
        if len(lista) == 1:
            return lista[0]
        if not lista:
            log.warning(
                "BIODATA: busca por prontuario %s vazia — "
                "tentando login completo e nova busca.",
                pront,
            )
            self._recuperar_sessao_e_cadastro()
            lista = self._buscar_lista_no_dialogo(
                termo=pront, campo_sel=campo_sel, prontuario_alvo=pront
            )
            return lista[0] if len(lista) == 1 else None
        log.warning(
            "BIODATA: prontuario %s retornou %s resultado(s) — ambiguo.",
            pront,
            len(lista),
        )
        return None

    def buscar_por_nome(
        self,
        nome: str,
        prontuario: Optional[str] = None,
    ) -> list[PacienteDados]:
        self._ensure_browser()
        campo_sel = self._loc()["campo_busca_nome"]
        lista = self._buscar_lista_no_dialogo(
            termo=nome, campo_sel=campo_sel, prontuario_alvo=prontuario
        )
        if lista:
            return lista
        log.warning(
            "BIODATA: busca por nome vazia (%r) — "
            "tentando login completo e nova busca.",
            nome,
        )
        self._recuperar_sessao_e_cadastro()
        return self._buscar_lista_no_dialogo(
            termo=nome, campo_sel=campo_sel, prontuario_alvo=prontuario
        )

    def _localizar_opcoes_dropdown(self, termo: str):
        assert self._page is not None
        page = self._page
        loc = self._loc()
        dropdown_opts = page.locator(
            "#clienteCadastroId-ts-dropdown .option, #clienteCadastroId-ts-dropdown [data-selectable]"
        )
        try:
            dropdown_opts.first.wait_for(state="visible", timeout=8000)
        except Exception:
            page.wait_for_timeout(2000)

        opcao = dropdown_opts if dropdown_opts.count() else page.locator(loc["opcao_resultado"])
        filtradas = opcao.filter(has_text=termo)
        if filtradas.count() == 0 and termo.split():
            filtradas = opcao.filter(has_text=termo.split()[0])
        if filtradas.count() > 0:
            opcao = filtradas
        return opcao

    def _dialogo_pesquisar_cliente_aberto(self) -> bool:
        """True só se o modal Pesquisar Cliente (campo Tom Select) estiver visível."""
        assert self._page is not None
        page = self._page
        loc = self._loc()
        campo_sel = loc.get("campo_busca_nome")
        if campo_sel:
            try:
                campo = page.locator(campo_sel).last
                if campo.count() and campo.is_visible():
                    return True
            except Exception:
                pass
        try:
            titulo = page.get_by_text("Pesquisar Cliente", exact=False)
            return bool(titulo.count() and titulo.last.is_visible())
        except Exception:
            return False

    def _botao_pesquisar(self):
        """Localiza o botão Pesquisar visível na tela Cadastro (não um oculto)."""
        assert self._page is not None
        page = self._page
        loc = self._loc()
        sel = loc["botao_pesquisar"]
        visivel = page.locator(f"{sel} >> visible=true")
        if visivel.count():
            return visivel.last
        return page.get_by_role("button", name="Pesquisar").locator("visible=true").last

    def _fechar_dialogo_pesquisa(self) -> None:
        """Fecha só o modal Pesquisar Cliente — nunca Sair genérico (fecha o Cadastro)."""
        assert self._page is not None
        page = self._page
        loc = self._loc()
        if not self._dialogo_pesquisar_cliente_aberto():
            return
        for _ in range(6):
            if not self._dialogo_pesquisar_cliente_aberto():
                return
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(300)
            if not self._dialogo_pesquisar_cliente_aberto():
                return
            # Sair apenas no modal que contém o campo de busca
            try:
                campo_sel = loc.get("campo_busca_nome") or "#clienteCadastroId-ts-control"
                modal = page.locator(
                    ".MuiModal-root, .MuiDialog-root, [role='dialog']"
                ).filter(has=page.locator(campo_sel))
                sair = modal.locator("button:has-text('Sair')")
                if sair.count():
                    sair.last.click(timeout=1500)
                    page.wait_for_timeout(350)
            except Exception:
                pass

    def _garantir_botao_pesquisar(self) -> None:
        """Garante botão Pesquisar clicável. Menu só se Cadastro ainda não foi aberto."""
        assert self._page is not None
        page = self._page
        self._tratar_reauth_se_necessario()
        self._fechar_dialogo_pesquisa()
        botao = self._botao_pesquisar()
        try:
            botao.wait_for(state="visible", timeout=5000)
            return
        except Exception:
            pass
        if self._cadastro_aberto:
            # Nao reabrir pelo menu: tela ja deve estar aberta
            log.warning(
                "Botão Pesquisar ausente com Cadastro aberto — aguardando na tela atual."
            )
            botao = self._botao_pesquisar()
            botao.wait_for(state="visible", timeout=15000)
            return
        log.info("Botão Pesquisar ausente — abrindo Cadastro de Pacientes pelo menu.")
        self._abrir_cadastro_pacientes()
        self._botao_pesquisar().wait_for(state="visible", timeout=15000)

    def _clicar_pesquisar_e_buscar(self, termo: str, campo_sel: str) -> None:
        """Re-pesquisa na tela atual: só Pesquisar + nome (sem menu Atendimento)."""
        assert self._page is not None
        page = self._page
        self._tratar_reauth_se_necessario()
        self._fechar_dialogo_pesquisa()
        botao = self._botao_pesquisar()
        botao.wait_for(state="visible", timeout=15000)
        log.info("Pesquisando novamente na tela Cadastro (sem reabrir menu).")
        botao.click()
        campo = page.locator(campo_sel).last
        campo.wait_for(state="visible")
        campo.click()
        try:
            campo.fill("")
        except Exception:
            pass
        campo.type(termo, delay=50)

    def _abrir_dialogo_pesquisar_cliente(self, termo: str, campo_sel: str) -> None:
        assert self._page is not None
        page = self._page
        self._garantir_botao_pesquisar()
        log.info("Abrindo diálogo Pesquisar Cliente.")
        self._botao_pesquisar().click()
        campo = page.locator(campo_sel).last
        campo.wait_for(state="visible")
        campo.click()
        try:
            campo.fill("")
        except Exception:
            pass
        campo.type(termo, delay=50)

    def _confirmar_opcao_e_extrair(self, opcao_locator) -> Optional[PacienteDados]:
        assert self._page is not None
        page = self._page
        loc = self._loc()
        opcao_locator.click()
        page.locator(loc["botao_confirmar_pesquisa"]).last.click()
        page.wait_for_timeout(1200)
        self._tratar_reauth_se_necessario()
        return self._extrair_cadastro()

    def _selecionar_candidato_por_texto(self, opcoes, texto: str, idx: int):
        primeira_linha = texto.splitlines()[0].strip() if texto else ""
        alvo = opcoes.filter(has_text=primeira_linha) if primeira_linha else opcoes
        if alvo.count() == 0:
            if idx < opcoes.count():
                return opcoes.nth(idx)
            return None
        return alvo.first

    def _buscar_lista_no_dialogo(
        self,
        termo: str,
        campo_sel: str,
        prontuario_alvo: Optional[str] = None,
    ) -> list[PacienteDados]:
        assert self._page is not None
        self._abrir_dialogo_pesquisar_cliente(termo, campo_sel)
        opcao = self._localizar_opcoes_dropdown(termo)
        count_opts = opcao.count()
        if count_opts == 0:
            log.warning("Nenhuma opção de resultado no Tom Select.")
            self._fechar_dialogo_pesquisa()
            return []

        if count_opts == 1:
            dados = self._confirmar_opcao_e_extrair(opcao.first)
            return [dados] if dados else []

        pront = prontuario_so_digitos(prontuario_alvo or "")
        if pront:
            for i in range(count_opts):
                texto = (opcao.nth(i).inner_text() or "").strip()
                if opcao_contem_prontuario(texto, pront):
                    log.info(
                        "Desambiguação por prontuario %s — opção %s/%s: %r",
                        pront,
                        i + 1,
                        count_opts,
                        texto[:80].replace("\n", " | "),
                    )
                    dados = self._confirmar_opcao_e_extrair(opcao.nth(i))
                    if dados:
                        atual = (dados.nome or "").strip()
                        limpo = sanitizar_nome_opcao(atual or texto, pront)
                        dados.nome = limpo or None
                        if not (dados.id_paciente or "").strip():
                            dados.id_paciente = pront
                        return [dados]
                    break
            log.warning(
                "Prontuario %s nao encontrado nas %s opcoes de %r — "
                "fallback desambiguacao por CPF.",
                pront,
                count_opts,
                termo,
            )

        # Varios resultados: abrir cada ficha (ate 10) para ler CPF
        textos: list[str] = []
        for i in range(min(count_opts, 10)):
            texto = (opcao.nth(i).inner_text() or "").strip()
            if texto:
                textos.append(texto)

        resultados: list[PacienteDados] = []
        for idx, texto in enumerate(textos):
            log.info(
                "Candidato ambíguo %s/%s: abrindo cadastro '%s'",
                idx + 1,
                len(textos),
                texto[:80].replace("\n", " | "),
            )
            # 1º: dialogo ja aberto; demais: so Pesquisar de novo (sem menu)
            if idx == 0:
                opcoes = opcao
            else:
                self._clicar_pesquisar_e_buscar(termo, campo_sel)
                opcoes = self._localizar_opcoes_dropdown(termo)
            alvo = self._selecionar_candidato_por_texto(opcoes, texto, idx)
            if alvo is None:
                self._fechar_dialogo_pesquisa()
                continue
            dados = self._confirmar_opcao_e_extrair(alvo)
            if dados:
                if not (dados.nome or "").strip():
                    limpo = sanitizar_nome_opcao(texto)
                    if limpo:
                        dados.nome = limpo
                else:
                    # Se extracao trouxe so ID/prontuario, limpa
                    limpo = sanitizar_nome_opcao(dados.nome or "")
                    if limpo and limpo != (dados.nome or "").strip():
                        dados.nome = limpo
                    elif not limpo:
                        limpo2 = sanitizar_nome_opcao(texto)
                        dados.nome = limpo2 or None
                resultados.append(dados)
                tem_cpf = tem_cpf_valido(dados.cpf)
                log.info(
                    "Candidato '%s' CPF=%s",
                    (dados.nome or texto)[:60].replace("\n", " "),
                    "sim" if tem_cpf else "nao",
                )
                if tem_cpf:
                    log.info(
                        "CPF encontrado no candidato %s/%s — não abre os demais.",
                        idx + 1,
                        len(textos),
                    )
                    break
            # Cadastro permanece aberto — espera Pesquisar para o proximo
            if idx < len(textos) - 1:
                try:
                    self._botao_pesquisar().wait_for(state="visible", timeout=8000)
                except Exception:
                    self._page.wait_for_timeout(500)
                self._fechar_dialogo_pesquisa()

        com_cpf = sum(1 for p in resultados if (p.cpf or "").strip())
        log.info(
            "Busca ambígua '%s': %s cadastro(s) abertos, %s com CPF.",
            termo,
            len(resultados),
            com_cpf,
        )
        return resultados

    def ler_cadastro_aberto(self) -> PacienteDados:
        """
        Relê os campos do cadastro ja aberto na pagina (sem Pesquisar/prontuario).
        """
        self._ensure_browser()
        return self._extrair_cadastro()

    def _extrair_cadastro(self) -> PacienteDados:
        assert self._page is not None
        loc = self._loc()
        page = self._page

        def text_of(key: str) -> Optional[str]:
            sel = loc.get(key)
            if not sel:
                return None
            el = page.locator(sel).last
            if el.count() == 0:
                return None
            try:
                if _is_input(el):
                    value = el.input_value()
                else:
                    value = el.inner_text()
            except Exception:
                try:
                    value = el.inner_text()
                except Exception:
                    return None
            value = (value or "").strip()
            return value or None

        cep = normalizar_cep_biodata(text_of("campo_cep"))
        endereco = text_of("campo_endereco")
        bairro = text_of("campo_bairro")
        ts_attrs = self._ler_attrs_item_cep_tomselect()
        if ts_attrs:
            cep, endereco, bairro = mesclar_endereco_tomselect_cep(
                cep=cep,
                endereco=endereco,
                bairro=bairro,
                data_value=ts_attrs.get("data-value"),
                data_endereco=ts_attrs.get("data-endereco"),
                data_bairro=ts_attrs.get("data-bairro"),
                item_text=ts_attrs.get("text"),
            )

        return PacienteDados(
            id_paciente=text_of("campo_id_paciente"),
            cpf=text_of("campo_cpf"),
            cns=text_of("campo_cns"),
            nome=text_of("campo_nome"),
            nome_mae=text_of("campo_nome_mae"),
            nascimento=text_of("campo_nascimento"),
            sexo=sexo_para_apac(text_of("campo_sexo")),
            endereco=endereco,
            cep=cep,
            logradouro=text_of("campo_logradouro"),
            bairro=bairro,
            numero=text_of("campo_numero"),
            complemento=text_of("campo_complemento"),
        )

    def _ler_attrs_item_cep_tomselect(self) -> Optional[dict[str, str]]:
        """Le .item do Tom Select CEP (#cepCliente) — data-value/endereco/bairro."""
        assert self._page is not None
        page = self._page
        item = page.locator(
            "select#cepCliente + .ts-wrapper .ts-control .item, "
            ".ts-wrapper:has(#cepCliente-ts-control) .ts-control .item"
        ).last
        try:
            if item.count() == 0:
                return None
            attrs = item.evaluate(
                """el => ({
                    'data-value': el.getAttribute('data-value') || '',
                    'data-endereco': el.getAttribute('data-endereco') || '',
                    'data-bairro': el.getAttribute('data-bairro') || '',
                    'text': (el.textContent || '').trim()
                })"""
            )
            if not isinstance(attrs, dict):
                return None
            out = {k: str(v).strip() for k, v in attrs.items() if v}
            return out or None
        except Exception:
            return None

    def _sair_ao_finalizar_ativo(self) -> bool:
        raw = self.cfg.biodata.get("sair_ao_finalizar", False)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "sim", "yes"}
        return bool(raw)

    def sair_para_login(self) -> None:
        """
        Logout UI: menu usuario (se houver) + Sair → tela de login.
        Usado em testes com biodata.sair_ao_finalizar.
        """
        if self._page is None:
            return
        page = self._page
        logout = dict(DEFAULT_LOGOUT_LOCATORS)
        logout.update(
            {
                k: v
                for k, v in (self.cfg.biodata.get("logout") or {}).items()
                if v
            }
        )
        locs = login_locators(self.cfg)
        log.info("BIODATA: saindo para tela de login (Sair).")
        try:
            self._fechar_dialogo_pesquisa()
        except Exception:
            pass
        _dismiss_blocking_overlays(page, self.cfg)
        menu_sel = str(logout.get("menu_usuario") or "")
        if menu_sel:
            try:
                menu = page.locator(menu_sel)
                if menu.count() and menu.first.is_visible():
                    menu.first.click(timeout=5000)
                    page.wait_for_timeout(400)
            except Exception as exc:
                log.debug("Menu usuario logout: %s", exc)
        botao_sel = str(
            logout.get("botao_sair") or DEFAULT_LOGOUT_LOCATORS["botao_sair"]
        )
        clicou = False
        try:
            botao = page.get_by_role("button", name="Sair")
            if botao.count():
                # Evita Sair do modal Pesquisar Cliente: preferir o ultimo visivel
                for i in range(botao.count() - 1, -1, -1):
                    b = botao.nth(i)
                    try:
                        if b.is_visible():
                            b.click(timeout=5000)
                            clicou = True
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        if not clicou:
            page.locator(botao_sel).last.click(timeout=8000)
            clicou = True
        page.wait_for_timeout(1000)
        try:
            page.locator(locs["campo_usuario"]).first.wait_for(
                state="visible", timeout=10000
            )
            log.info("BIODATA: tela de login apos Sair.")
        except Exception:
            log.warning(
                "BIODATA: Sair clicado, mas campo usuario nao confirmado."
            )

    def close(self) -> None:
        try:
            if self._sair_ao_finalizar_ativo() and self._page is not None:
                try:
                    self.sair_para_login()
                except Exception as exc:
                    log.warning(
                        "BIODATA: falha ao sair para login ao finalizar: %s",
                        exc,
                    )
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            self._cadastro_aberto = False
            if getattr(self, "_pw", None) is not None:
                self._pw.stop()
                self._pw = None


def _titulo_reauth(cfg: Optional[AppConfig] = None) -> str:
    if cfg is None:
        return str(DEFAULT_REAUTH_LOCATORS["titulo"])
    reauth = cfg.biodata.get("reauth") or {}
    raw = str(reauth.get("titulo") or DEFAULT_REAUTH_LOCATORS["titulo"])
    # Aceita valor legado "text=Autenticação" do config antigo
    if raw.lower().startswith("text="):
        return raw.split("=", 1)[1].strip()
    return raw


def modal_reauth_visivel(page, cfg: Optional[AppConfig] = None) -> bool:
    """True se o modal Autenticação (reauth pos-token) estiver na tela."""
    titulo = _titulo_reauth(cfg)
    try:
        if page.get_by_role("heading", name=titulo).count() > 0:
            return True
        if page.get_by_text(titulo, exact=False).count() > 0:
            return True
        dialog = page.get_by_role("dialog")
        if dialog.count() and dialog.filter(has_text=titulo).count() > 0:
            return True
    except Exception:
        return False
    return False


def tratar_reauth_se_necessario(page, cfg: AppConfig) -> None:
    """
    Modal Autenticação: usuario ja vem preenchido — digita so a senha,
    clica LOGIN e recarrega (F5). Usado na abertura e no meio do fluxo.
    """
    if not modal_reauth_visivel(page, cfg):
        return
    reauth = cfg.biodata.get("reauth") or {}
    titulo = _titulo_reauth(cfg)
    log.info("Modal de reautenticação detectado; preenchendo senha.")
    creds = load_biodata_credentials(cfg)
    if creds is None:
        input("Faça a autenticação no navegador e pressione Enter...")
        return
    senha_sel = str(
        reauth.get("campo_senha")
        or DEFAULT_REAUTH_LOCATORS["campo_senha"]
    )
    # No modal o campo Senha pode ser type=text
    campo = page.get_by_role("textbox", name="Senha")
    if campo.count():
        campo.first.fill(creds.senha)
    else:
        page.locator(senha_sel).last.fill(creds.senha)
    botao = page.get_by_role("button", name="Login")
    if botao.count():
        botao.first.click()
    else:
        page.locator(
            str(reauth.get("botao_login") or DEFAULT_REAUTH_LOCATORS["botao_login"])
        ).last.click()
    page.wait_for_timeout(1500)
    try:
        page.get_by_role("heading", name=titulo).first.wait_for(
            state="hidden", timeout=10000
        )
    except Exception:
        pass
    # Fluxo manual confirmado: senha → LOGIN → F5
    log.info("Reauth LOGIN ok — recarregando pagina (F5).")
    try:
        page.reload(wait_until="domcontentloaded")
    except Exception as exc:
        log.warning("Reload apos reauth falhou: %s", exc)
        return
    page.wait_for_timeout(900)
    if modal_reauth_visivel(page, cfg):
        log.warning(
            "Modal Autenticação ainda visivel apos F5 — "
            "verifique senha em secrets.local.json."
        )


def login_locators(cfg: AppConfig) -> dict[str, str]:
    configured = (cfg.biodata.get("login") or {}).get("locators") or {}
    merged = dict(DEFAULT_LOGIN_LOCATORS)
    for key, value in configured.items():
        if value:
            merged[key] = str(value)
    return merged


def _login_url_patterns(locs: dict) -> list[str]:
    raw = locs.get("url_apos_login") or ["**/home*", "**/consultorio/**"]
    if isinstance(raw, str):
        return [raw]
    return [str(x) for x in raw if x]


def _path_indica_logado(url: str) -> bool:
    path = (url or "").lower()
    return "/home" in path or "/consultorio" in path


def _ja_logado(page, locs: dict[str, str]) -> bool:
    try:
        if _path_indica_logado(page.url or ""):
            return True
    except Exception:
        pass
    indicador = locs.get("indicador_logado")
    if not indicador:
        return False
    try:
        loc = page.locator(indicador)
        if loc.count() == 0:
            return False
        return bool(loc.first.is_visible())
    except Exception:
        return False


def _pagina_autenticada(page, locs: dict[str, str]) -> bool:
    """True se a página já está na área logada (URL, indicador ou menu)."""
    try:
        if page.is_closed():
            return False
    except Exception:
        return False
    return bool(_ja_logado(page, locs) or _menu_lateral_visivel(page))


def _sessao_biodata_ok(page, cfg: AppConfig) -> bool:
    """Sessao usavel: area logada e sem modal Autenticacao bloqueando."""
    locs = login_locators(cfg)
    return (
        (_pagina_autenticada(page, locs) or _menu_lateral_visivel(page))
        and not modal_reauth_visivel(page, cfg)
    )


def _escolher_pagina_ja_logada(context, locs: dict[str, str]):
    """
    Retorna a primeira aba já autenticada do contexto, ou None.
    Evita goto na URL de login quando a sessão do perfil ainda vale.
    """
    try:
        pages = list(context.pages)
    except Exception:
        return None
    for page in pages:
        if _pagina_autenticada(page, locs):
            return page
    return None


def _tem_application_error(page) -> bool:
    """Next.js / client crash: 'Application error: a client-side exception...'."""
    try:
        for texto in ("Application error", "client-side exception"):
            loc = page.get_by_text(texto, exact=False)
            if loc.count() and loc.first.is_visible():
                return True
    except Exception:
        pass
    try:
        body = (page.locator("body").inner_text(timeout=2000) or "").lower()
        return "application error" in body and "client-side exception" in body
    except Exception:
        return False


def _recarregar_apos_application_error(page, cfg: AppConfig) -> None:
    """F5 / reload; se o erro persistir, tenta /home e por fim a URL base."""
    log.warning("BIODATA Application error detectado — recarregando (F5).")
    try:
        page.reload(wait_until="domcontentloaded")
    except Exception:
        pass
    page.wait_for_timeout(1000)
    _dismiss_blocking_overlays(page)
    if not _tem_application_error(page):
        return
    home = _url_home_biodata(cfg)
    if home:
        log.warning("Application error persiste — tentando home %s.", home)
        try:
            page.goto(home, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            _dismiss_blocking_overlays(page)
            if not _tem_application_error(page):
                return
        except Exception as exc:
            log.warning("Falha ao abrir home apos Application error: %s", exc)
    url = (cfg.biodata or {}).get("url")
    if url:
        log.warning("Application error persiste — abrindo URL base do BIODATA.")
        page.goto(str(url), wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        _dismiss_blocking_overlays(page)


def _abrir_ou_reusar_sessao(page, cfg: AppConfig) -> None:
    """
    Abre /home com o perfil persistente. Se a sessao de ~4h ainda vale,
    nao faz login. Se reauth (senha+LOGIN+F5) falhar, login completo em biodata.url.
    """
    home = _url_home_biodata(cfg)
    if not home:
        raise BiodataMappingError(
            "biodata.url e obrigatorio para abrir /home (reuso de sessao)."
        )

    log.info("Abrindo BIODATA em %s (reuso de sessao se ainda valida).", home)
    try:
        page.goto(home, wait_until="domcontentloaded")
    except Exception as exc:
        log.warning("Falha ao abrir home (%s): %s — tentando URL base.", home, exc)
        url = (cfg.biodata or {}).get("url")
        if not url:
            raise BiodataMappingError(str(exc)) from exc
        page.goto(str(url), wait_until="domcontentloaded")

    page.wait_for_timeout(800)
    _dismiss_blocking_overlays(page, cfg)
    # Token expirado: modal Autenticacao (usuario fixo) — senha antes de achar sessao "ok"
    tratar_reauth_se_necessario(page, cfg)

    if _tem_application_error(page):
        _recarregar_apos_application_error(page, cfg)

    if _sessao_biodata_ok(page, cfg):
        log.info("Sessão BIODATA válida — /home sem novo login.")
        return

    # Cookie pode demorar a aplicar / redirect ainda em curso
    try:
        page.wait_for_function(
            """() => {
              const p = (location.pathname || '').toLowerCase();
              return p.includes('/home') || p.includes('/consultorio');
            }""",
            timeout=5000,
        )
        _dismiss_blocking_overlays(page, cfg)
        tratar_reauth_se_necessario(page, cfg)
        if _sessao_biodata_ok(page, cfg):
            log.info("Sessão BIODATA válida — /home sem novo login.")
            return
    except Exception:
        pass

    log.info(
        "Sessão BIODATA nao confirmada apos reauth — "
        "voltando a tela de login (fluxo completo)."
    )
    ensure_biodata_login(page, cfg, force_full=True)

    if _sessao_biodata_ok(page, cfg):
        log.info("Sessão BIODATA confirmada apos login completo.")
        return

    # Ultimo retry: /home + reauth leve (sem loop de force_full)
    try:
        page.goto(home, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        _dismiss_blocking_overlays(page, cfg)
        tratar_reauth_se_necessario(page, cfg)
    except Exception as exc:
        log.warning("Retry /home apos login falhou: %s", exc)
    if _sessao_biodata_ok(page, cfg):
        log.info("Sessão BIODATA confirmada apos login/home.")
        return
    raise BiodataMappingError(
        "Nao foi possivel confirmar sessao BIODATA em /home apos login. "
        "Verifique credenciais em secrets.local.json ou faca login manual uma vez."
    )


def ensure_biodata_login(
    page, cfg: AppConfig, *, force_full: bool = False
) -> None:
    locs = login_locators(cfg)

    if force_full:
        url_login = (cfg.biodata or {}).get("url")
        if not url_login:
            raise BiodataMappingError(
                "biodata.url e obrigatorio para login completo."
            )
        log.info("Login completo: abrindo tela de login %s", url_login)
        page.goto(str(url_login), wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        _dismiss_blocking_overlays(page, cfg)
        if _tem_application_error(page):
            _recarregar_apos_application_error(page, cfg)
        try:
            page.locator(locs["campo_usuario"]).first.wait_for(
                state="visible", timeout=15000
            )
        except Exception as exc:
            raise BiodataMappingError(
                "Tela de login BIODATA nao exibiu campo usuario. "
                f"Verifique biodata.url ({url_login})."
            ) from exc
        precisa_login = True
    else:
        # Modal reauth (senha) antes do formulario completo de login
        tratar_reauth_se_necessario(page, cfg)
        if _sessao_biodata_ok(page, cfg):
            log.info("Sessão BIODATA já autenticada — sem novo login.")
            return
        _dismiss_blocking_overlays(page, cfg)
        page.wait_for_timeout(500)

        if _tem_application_error(page):
            _recarregar_apos_application_error(page, cfg)

        # Sessão já autenticada: home / menu lateral (inputs de login podem existir ocultos no DOM)
        if _pagina_autenticada(page, locs) and not modal_reauth_visivel(page, cfg):
            log.info("Sessão BIODATA já autenticada — sem novo login.")
            return

        campo = page.locator(locs["campo_usuario"]).first
        try:
            precisa_login = campo.is_visible(timeout=2500) and campo.is_enabled()
        except Exception:
            precisa_login = False

        if not precisa_login:
            # Pode estar redirecionando para /home ou /consultorio
            try:
                page.wait_for_function(
                    """() => {
                      const p = (location.pathname || '').toLowerCase();
                      return p.includes('/home') || p.includes('/consultorio');
                    }""",
                    timeout=8000,
                )
                log.info("Sessão BIODATA já autenticada.")
                return
            except Exception:
                pass
            try:
                page.wait_for_selector("#menuLateral", state="visible", timeout=3000)
                log.info("Sessão BIODATA já autenticada.")
                return
            except Exception:
                precisa_login = False

        if not precisa_login:
            if _tem_application_error(page):
                _recarregar_apos_application_error(page, cfg)
                campo = page.locator(locs["campo_usuario"]).first
                try:
                    precisa_login = (
                        campo.is_visible(timeout=4000) and campo.is_enabled()
                    )
                except Exception:
                    precisa_login = False
            # Preferir /home (sessao) em vez de forcar URL de login
            home = _url_home_biodata(cfg)
            if not precisa_login and home:
                try:
                    page.goto(home, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)
                    _dismiss_blocking_overlays(page, cfg)
                except Exception as exc:
                    log.warning(
                        "ensure_biodata_login: falha ao abrir home: %s", exc
                    )
                if _tem_application_error(page):
                    _recarregar_apos_application_error(page, cfg)
                if _sessao_biodata_ok(page, cfg):
                    log.info("Sessão BIODATA já autenticada — sem novo login.")
                    return
                campo = page.locator(locs["campo_usuario"]).first
                try:
                    precisa_login = (
                        campo.is_visible(timeout=4000) and campo.is_enabled()
                    )
                except Exception:
                    precisa_login = False
            if not precisa_login:
                if _sessao_biodata_ok(page, cfg):
                    log.info("Sessão BIODATA já autenticada — sem novo login.")
                    return
                raise BiodataMappingError(
                    "Não foi possível entrar no BIODATA "
                    "(login indisponível e sessão não confirmada). "
                    "Feche outras abas/sessões do BIODATA e tente novamente."
                )

    # Última checagem: nunca preencher login se a sessão voltou no meio do fluxo
    if _pagina_autenticada(page, locs):
        log.info("Sessão BIODATA já autenticada — sem novo login.")
        return

    try:
        creds = load_biodata_credentials(cfg)
    except SecretsError as exc:
        raise BiodataMappingError(str(exc)) from exc

    if creds is None:
        log.info(
            "Arquivo de segredos não encontrado. Login manual: "
            "crie secrets.local.json a partir de secrets.example.json para automatizar."
        )
        input("Após o login no BIODATA, pressione Enter neste terminal para continuar...")
        return

    timeout_ms = int(cfg.timeouts.get("biodata_ms", 15000))
    ultimo_erro: Optional[Exception] = None
    for tentativa in range(1, 4):
        log.info(
            "Realizando login automático no BIODATA (credenciais locais) — tentativa %s/3.",
            tentativa,
        )
        if _tem_application_error(page):
            _recarregar_apos_application_error(page, cfg)
        # Joyride/tutorial frequentemente bloqueia o botão Entrar em perfil novo
        for _ in range(3):
            _dismiss_blocking_overlays(page)
            page.wait_for_timeout(200)
        try:
            page.fill(locs["campo_usuario"], creds.usuario)
            page.fill(locs["campo_senha"], creds.senha)
        except Exception as exc:
            ultimo_erro = exc
            log.warning("Falha ao preencher login (tentativa %s/3): %s", tentativa, exc)
            _recarregar_apos_application_error(page, cfg)
            continue
        for _ in range(3):
            _dismiss_blocking_overlays(page)
            page.wait_for_timeout(150)
        _click_login(page, locs["botao_entrar"])
        page.wait_for_timeout(800)
        if _tem_application_error(page):
            log.warning(
                "Application error após Entrar (tentativa %s/3) — F5 e nova tentativa.",
                tentativa,
            )
            _recarregar_apos_application_error(page, cfg)
            continue
        try:
            _aguardar_login_ok(page, locs, timeout_ms)
            log.info("Login automático concluído.")
            return
        except Exception as exc:
            ultimo_erro = exc
            if _tem_application_error(page):
                log.warning(
                    "Application error aguardando pós-login (tentativa %s/3).",
                    tentativa,
                )
            else:
                log.warning("Login não confirmado (tentativa %s/3): %s", tentativa, exc)
            if tentativa < 3:
                _recarregar_apos_application_error(page, cfg)

    if isinstance(ultimo_erro, BiodataMappingError):
        raise ultimo_erro
    raise BiodataMappingError(
        "Login automático falhou após 3 tentativas (Application error ou timeout). "
        "Verifique usuário/senha e tente novamente."
    ) from ultimo_erro


def _menu_lateral_visivel(page) -> bool:
    try:
        menu = page.locator("#menuLateral")
        return menu.count() > 0 and menu.first.is_visible()
    except Exception:
        return False


def _url_home_biodata(cfg: AppConfig) -> Optional[str]:
    """Deriva .../home a partir de biodata.url (ex.: .../oftalmocentro91 -> .../oftalmocentro91/home)."""
    raw = (cfg.biodata or {}).get("url")
    if not raw:
        return None
    base = str(raw).rstrip("/")
    # URL de login costuma ser o tenant; home = tenant/home
    if base.lower().endswith("/home"):
        return base
    return f"{base}/home"


def _aguardar_menu_lateral(page, cfg: AppConfig, *, timeout_ms: int) -> None:
    """
    Espera #menuLateral apos login. Em /consultorio o menu pode demorar ou
    nao existir — tenta overlays, reload e fallback para /home.
    """
    import time as _time

    def _tentar(ate_ms: float) -> bool:
        fim = _time.time() + ate_ms / 1000.0
        while _time.time() < fim:
            _dismiss_blocking_overlays(page)
            if _menu_lateral_visivel(page):
                return True
            page.wait_for_timeout(400)
        return _menu_lateral_visivel(page)

    if _tentar(min(8000, timeout_ms)):
        return

    log.warning(
        "Menu lateral (#menuLateral) ausente em %s — recarregando pagina.",
        page.url,
    )
    try:
        page.reload(wait_until="domcontentloaded")
    except Exception:
        pass
    page.wait_for_timeout(1000)
    if _tentar(min(8000, timeout_ms)):
        return

    home = _url_home_biodata(cfg)
    if home and "/home" not in (page.url or "").lower():
        log.warning(
            "Menu lateral ainda ausente — abrindo home %s (rota consultorio sem menu).",
            home,
        )
        try:
            page.goto(home, wait_until="domcontentloaded")
        except Exception as exc:
            log.warning("Falha ao abrir home: %s", exc)
        page.wait_for_timeout(1000)
        _dismiss_blocking_overlays(page)
        if _tentar(timeout_ms):
            return

    raise BiodataMappingError(
        "Menu lateral (#menuLateral) nao ficou visivel apos o login "
        f"(url={page.url}). Feche overlays/tutoriais no BIODATA e tente de novo, "
        "ou abra o modulo Atendimento manualmente e rode outra vez."
    )


def _aguardar_login_ok(page, locs: dict[str, str], timeout: int) -> None:
    indicador = locs.get("indicador_logado")
    # Aceita /home (atendimento) ou /consultorio/... (consultório)
    try:
        page.wait_for_function(
            """() => {
              const p = (location.pathname || '').toLowerCase();
              return p.includes('/home') || p.includes('/consultorio');
            }""",
            timeout=timeout,
        )
        log.info("Pós-login em %s", page.url)
        return
    except Exception:
        pass
    for url_pat in _login_url_patterns(locs):
        try:
            page.wait_for_url(url_pat, timeout=min(3000, timeout))
            log.info("Pós-login em %s", page.url)
            return
        except Exception:
            continue
    if indicador:
        try:
            page.locator(indicador).first.wait_for(state="visible", timeout=timeout)
            return
        except Exception:
            pass
    raise BiodataMappingError(
        "Login automático não confirmou sucesso. "
        "Verifique usuário/senha em secrets.local.json "
        "(e se algum tutorial/overlay bloqueou o botão Entrar)."
    )


def _dismiss_blocking_overlays(page, cfg: Optional[AppConfig] = None) -> None:
    # Escape cancela o modal Autenticacao — nao dismiss enquanto estiver aberto
    if modal_reauth_visivel(page, cfg):
        return
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    for name in ("Fechar", "Skip", "Pular", "Close", "Got it", "Next"):
        btn = page.get_by_role("button", name=name)
        try:
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1000)
        except Exception:
            continue
    try:
        page.evaluate(
            """() => {
              document.querySelectorAll(
                '#react-joyride-portal, .react-joyride__overlay, [data-test-id="overlay"]'
              ).forEach(el => el.remove());
            }"""
        )
    except Exception:
        pass


def _click_login(page, botao_selector: str) -> None:
    botao = page.locator(botao_selector).first
    try:
        botao.click(timeout=5000)
        return
    except Exception:
        pass
    try:
        botao.click(force=True, timeout=5000)
        return
    except Exception:
        pass
    senha = page.locator("input[name='password']").first
    try:
        if senha.count() and senha.is_visible():
            senha.press("Enter")
            return
    except Exception:
        pass
    page.keyboard.press("Enter")


def _is_input(locator) -> bool:
    try:
        name = locator.evaluate("el => el.tagName")
        return str(name).lower() in {"input", "textarea", "select"}
    except Exception:
        return False


def normalizar_cep_biodata(valor: Optional[str]) -> Optional[str]:
    """Extrai CEP de 8 digitos (ou None)."""
    if not valor:
        return None
    digitos = "".join(ch for ch in str(valor) if ch.isdigit())
    if len(digitos) >= 8:
        return digitos[:8]
    return None


def mesclar_endereco_tomselect_cep(
    *,
    cep: Optional[str],
    endereco: Optional[str],
    bairro: Optional[str],
    data_value: Optional[str] = None,
    data_endereco: Optional[str] = None,
    data_bairro: Optional[str] = None,
    item_text: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Completa cep/endereco/bairro a partir do .item Tom Select do CEP.
    Nao sobrescreve valores ja presentes.
    """
    if not cep:
        cep = normalizar_cep_biodata(data_value) or normalizar_cep_biodata(item_text)
    if not (endereco or "").strip() and (data_endereco or "").strip():
        endereco = str(data_endereco).strip()
    if not (bairro or "").strip() and (data_bairro or "").strip():
        bairro = str(data_bairro).strip()
    return cep, endereco, bairro


def open_biodata_session(cfg: AppConfig) -> None:
    """Abre BIODATA, faz login e navega até Cadastro de Pacientes (se mapeado)."""
    from playwright.sync_api import sync_playwright

    biodata = cfg.biodata
    url = biodata.get("url")
    if not url:
        raise BiodataMappingError("biodata.url é obrigatório para abrir a sessão.")

    base = config_dir(cfg)
    user_data = resolve_path(
        base, Path(str(biodata.get("user_data_dir", "browser_profile")))
    )
    user_data.mkdir(parents=True, exist_ok=True)
    timeout = int(cfg.timeouts.get("biodata_ms", 15000))

    log.info("Abrindo BIODATA (perfil local dedicado — reuso de /home).")
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        try:
            locs = login_locators(cfg)
            page = _escolher_pagina_ja_logada(context, locs)
            if page is not None:
                page.set_default_timeout(timeout)
                log.info("Aba BIODATA ja autenticada — reutilizando.")
            else:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(timeout)
            _abrir_ou_reusar_sessao(page, cfg)
            pendentes = biodata_locators_pendentes(cfg)
            if not pendentes:
                # Reutiliza a lógica do conector sem bloquear no __init__ por estado
                tmp = object.__new__(BiodataConnector)
                tmp.cfg = cfg
                tmp._page = page
                tmp._cadastro_aberto = False
                tmp._abrir_cadastro_pacientes()
            else:
                log.warning(
                    "Navegação até cadastro ainda incompleta: %s",
                    ", ".join(pendentes),
                )
            input("Navegador aberto. Pressione Enter neste terminal para fechar...")
        finally:
            context.close()
    log.info("Sessão encerrada. Perfil mantido em %s", user_data)
