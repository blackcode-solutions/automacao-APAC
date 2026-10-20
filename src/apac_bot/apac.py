from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
import unicodedata
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from apac_bot.config import (
    MODALIDADE_GLAUCOMA,
    AppConfig,
    config_dir,
    fim_offset_meses,
    resolve_path,
)
from apac_bot.connectors import BiodataMappingError, build_connector
from apac_bot.console_screen import (
    CampoApac,
    ConsoleScreenError,
    TelaApac,
    campo_compativel,
    classificar_tela,
    extrair_valor_campo_linha,
    identificar_campo_cursor,
    ler_buffer_apac,
    ler_valor_campo_cursor,
    preview_tela,
)

# Pausas do open-apac — perfil via apac.velocidade (seguro|rapido).
# `rapido` e agressivo; se Magnético engolir teclas, volte para `seguro`.
_TIMINGS_SEGURO: dict[str, float] = {
    "pre_campo": 1.0,
    "pos_digitar": 0.6,
    "pos_digitar_cnes": 1.2,
    "pos_digitar_curto": 0.5,
    "pos_tab": 0.85,
    "pos_tab_apos_aceitar": 0.9,
    "pos_sem_tab": 0.45,
    "pos_enter_form": 1.0,
    "enter_solto_timeout": 2.0,
    "enter_solto_timeout_curto": 1.0,
    "enter_solto_settle": 0.18,
    "enter_solto_tail": 0.2,
    "nav_enter": 2.0,
    "pos_home": 0.1,
    "pos_apos_digitar_numero": 0.35,
    "pos_prontuario": 0.8,
    "pos_raca_pre": 0.6,
    "pos_raca_digitar": 0.5,
    "pos_insert": 1.0,
    "pos_tecla_foco": 0.12,
    "pos_nav_retry": 1.8,
    "pos_apos_ensure": 1.0,
    "pos_proc_digitar": 0.4,
    "pos_proc_tab": 0.45,
    "pos_f1": 0.8,
    "char_down": 0.035,
    "char_up": 0.045,
}
_TIMINGS_RAPIDO: dict[str, float] = {
    "pre_campo": 0.08,
    "pos_digitar": 0.15,
    "pos_digitar_cnes": 0.18,
    "pos_digitar_curto": 0.12,
    "pos_tab": 0.12,
    "pos_tab_apos_aceitar": 0.12,
    "pos_sem_tab": 0.08,
    "pos_enter_form": 0.22,
    "enter_solto_timeout": 0.15,
    "enter_solto_timeout_curto": 0.15,
    "enter_solto_settle": 0.02,
    "enter_solto_tail": 0.02,
    "nav_enter": 0.4,
    "pos_home": 0.03,
    "pos_apos_digitar_numero": 0.08,
    "pos_prontuario": 0.18,
    "pos_raca_pre": 0.12,
    "pos_raca_digitar": 0.12,
    "pos_insert": 0.22,
    "pos_tecla_foco": 0.03,
    "pos_nav_retry": 0.3,
    "pos_apos_ensure": 0.2,
    "pos_proc_digitar": 0.06,
    "pos_proc_tab": 0.08,
    "pos_f1": 0.18,
    "char_down": 0.015,
    "char_up": 0.020,
}
_timings_ativos: dict[str, float] = dict(_TIMINGS_SEGURO)


def aplicar_velocidade_apac(perfil: str) -> str:
    """
    Ativa tabela de pausas. Retorna nome normalizado (seguro|rapido).

    `rapido` e o perfil agressivo (pausas curtas + digitacao rapida).
    Se o Magnético engolir teclas ou pular campos, use `seguro` como rollback.
    """
    global _timings_ativos
    nome = (perfil or "seguro").strip().lower()
    if nome in {"rapido", "rápido", "fast", "quick"}:
        _timings_ativos = dict(_TIMINGS_RAPIDO)
        return "rapido"
    _timings_ativos = dict(_TIMINGS_SEGURO)
    return "seguro"


def timing_apac(chave: str, default: float = 0.0) -> float:
    return float(_timings_ativos.get(chave, default))

# Rotulos usados em _aceitar_campo_texto_se_preenchido / Tabs cegos
_ROTULO_PARA_CAMPO: dict[str, CampoApac] = {
    "NOME": CampoApac.NOME,
    "NOME DA MAE": CampoApac.NOME_MAE,
    "NOME DO RESPONSAVEL": CampoApac.RESPONSAVEL,
    "CEP": CampoApac.CEP,
    "LOGRADOURO": CampoApac.LOGRADOURO,
    "ENDERECO": CampoApac.ENDERECO,
    "NUMERO": CampoApac.NUMERO,
    "COMPLEMENTO": CampoApac.COMPLEMENTO,
    "BAIRRO": CampoApac.BAIRRO,
    "TELEFONE": CampoApac.TELEFONE,
    "EMAIL": CampoApac.EMAIL,
    "DATA DE NASCIMENTO": CampoApac.NASCIMENTO,
    "SEXO": CampoApac.SEXO,
    "RACA": CampoApac.ETNIA_RACA,
    "RACA/ETNIA": CampoApac.ETNIA_RACA,
}
from apac_bot.logging_safe import setup_logging
from apac_bot.models import EstadoLancamento, Lancamento
from apac_bot.normalize import (
    APAC_MAX_NOME,
    abreviar_nome_apac,
    nascimento_ddmmaaaa,
    sexo_para_apac,
    tipo_logradouro_do_endereco,
)
from apac_bot.progress import ProgressStore, filtrar_pendentes_lote
from apac_bot.set_layout import ultimo_dia_mes
from apac_bot.sheet import SheetError, listar_lancamentos_a_partir

log = setup_logging()


def datas_validade_mes_anterior(
    hoje: Optional[date] = None,
    fim_offset_meses: int = 0,
) -> tuple[str, str]:
    """
    Primeiro dia do mes anterior e ultimo dia de (mes anterior + offset),
    como DDMMAAAA (mascara APAC sem barras).
    Ex.: hoje 09/10/2026, offset 0 -> ('01092026', '30092026').
    Ex.: hoje 09/10/2026, offset 2 -> ('01092026', '30112026') (Glaucoma).
    """
    ref = hoje or date.today()
    primeiro_mes_atual = ref.replace(day=1)
    ultimo_mes_ant = primeiro_mes_atual - timedelta(days=1)
    primeiro_mes_ant = ultimo_mes_ant.replace(day=1)
    fim = ultimo_dia_mes(
        primeiro_mes_ant.year, primeiro_mes_ant.month, fim_offset_meses
    )
    return (
        primeiro_mes_ant.strftime("%d%m%Y"),
        fim.strftime("%d%m%Y"),
    )


def _nome_profissional_f1(nome: str) -> str:
    """Nome para busca A-Z no menu F1 (maiusculo, sem acento)."""
    t = unicodedata.normalize("NFKD", (nome or "").strip())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    # Magnético: zero com barra (Ø) e digito 0 — digitar como '0'
    t = t.replace("\u00d8", "0").replace("\u00f8", "0")
    return t.upper()


def _norm_nome_profissional(nome: str) -> str:
    """
    Normaliza nome de profissional para comparacao.
    Maiusculo, sem acento; O e Ø equivalem a 0 (ex.: ORCELIO vs 0RCELIO no Magnético).
    """
    t = _nome_profissional_f1(nome)
    t = t.replace("O", "0")
    return " ".join(t.split())


def _nome_profissional_compativel(buscado: str, lido: str) -> bool:
    """
    True se o nome lido no APAC corresponde ao buscado.
    Aceita igualdade ou um contendo o outro (truncagem/extensao do Magnético).
    """
    a = _norm_nome_profissional(buscado)
    b = _norm_nome_profissional(lido)
    if not a or not b:
        return False
    if a == b:
        return True
    # Contencao de frase completa (nao so um token solto)
    return a in b or b in a


# Padroes da clinica exemplo (dados_fixos; dinamicos por clinica / UI futura).
# Selecao no Magnético e por CNS (nome so para confirmacao/label).
MEDICO_SOLICITANTE_CNS_PADRAO = "705609469670213"
MEDICO_SOLICITANTE_NOME_PADRAO = "0RCELIO REZENDE"
AUTORIZADOR_CNS_PADRAO = "708107527671032"
AUTORIZADOR_NOME_PADRAO = "MARQUES HENRIQUE MARTINS FEITO"
# Alias legado (testes / logs)
MEDICO_SOLICITANTE_PADRAO = MEDICO_SOLICITANTE_NOME_PADRAO


def _cns_so_digitos(valor: str) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def buscar_paciente_biodata(connector, lanc: Lancamento) -> str:
    """
    Resolve paciente no connector ja aberto; preenche lanc.paciente.
    Retorna CPF so com digitos.
    Ambiguidade / nao encontrado / dados obrigatorios faltando -> DadosIncompletosError
    (lote open-apac pula o paciente; nao aborta por cadastro incompleto).
    Nao fecha o connector (sessao permanece para nascimento/sexo).
    """
    # Import tardio: pipeline importa ApacAutomator (evita import circular)
    from apac_bot.pipeline import resolver_paciente, validar_dados_obrigatorios_apac

    paciente, motivo = resolver_paciente(connector, lanc)
    if motivo or paciente is None:
        msg = (
            f"BIODATA: nao foi possivel obter dados de '{lanc.paciente_nome}': "
            f"{motivo or 'paciente vazio'}"
        )
        raise DadosIncompletosError(msg, motivo=motivo or "paciente vazio")
    lanc.paciente = paciente
    faltando = validar_dados_obrigatorios_apac(paciente, lanc.paciente_nome)
    if faltando:
        msg = (
            f"BIODATA: dados obrigatorios incompletos para '{lanc.paciente_nome}' "
            f"({faltando})."
        )
        raise DadosIncompletosError(msg, motivo=faltando)
    cpf_raw = (paciente.cpf or "").strip()
    cpf = "".join(ch for ch in cpf_raw if ch.isdigit())
    log.info(
        "BIODATA: dados ok / CPF obtido para %s (id=%s)",
        lanc.paciente_nome,
        paciente.id_paciente or "—",
    )
    return cpf


def refrescar_paciente_biodata(connector, lanc: Lancamento) -> None:
    """
    Relê o cadastro ja aberto no BIODATA (sem Pesquisar / prontuario de novo).
    """
    ler = getattr(connector, "ler_cadastro_aberto", None)
    if not callable(ler):
        log.warning(
            "BIODATA: connector sem ler_cadastro_aberto — mantem cache de %s",
            lanc.paciente_nome,
        )
        return
    try:
        paciente = ler()
    except Exception as exc:
        log.warning(
            "BIODATA: falha ao ler cadastro aberto de %s: %s",
            lanc.paciente_nome,
            exc,
        )
        return
    if paciente is None:
        log.warning(
            "BIODATA: cadastro aberto vazio ao refrescar %s",
            lanc.paciente_nome,
        )
        return
    lanc.paciente = paciente
    log.info("BIODATA: dados do paciente atualizados (cadastro aberto).")


DEFAULT_APAC_EXE = Path(r"C:\APAC\APAC.exe")
APAC_PROCESS_NAME = "APAC.exe"
# Fallback quando BIODATA nao tem CEP (8 digitos) — evita Tab-pular e foco preso.
CEP_PADRAO_APAC = "65020070"
# APAC Magnético é console: a janela visível costuma ser do Windows Terminal / conhost
HOST_WINDOW_PROCESS_NAMES = {
    "apac.exe",
    "windowsterminal.exe",
    "openconsole.exe",
    "conhost.exe",
    "cmd.exe",
}
# Títulos que contêm "APAC" mas não são o Magnético
TITULO_EXCLUSOES = (
    "cursor",
    "chrome",
    "msedge",
    "firefox",
    "libreoffice",
    "notepad",
    "bloco de notas",
    ".xlsx",
    ".png",
    ".md",
    ".pdf",
    "photos",
    "automacao-apac",
    "automação-dg",
)


def pids_do_processo(nome_exe: str = APAC_PROCESS_NAME) -> list[int]:
    """PIDs de processos com o nome de imagem informado (Windows)."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {nome_exe}", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("INFO"):
            continue
        # "APAC.exe","1234","Console","1","12.345 K"
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower() == nome_exe.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


def _nome_processo_pid(pid: int) -> str:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2:
            try:
                if int(parts[1]) == pid:
                    return parts[0].lower()
            except ValueError:
                continue
    return ""


def titulo_hwnd(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def classe_hwnd(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


VK_RETURN = 0x0D
VK_TAB = 0x09
VK_INSERT = 0x2D
VK_F1 = 0x70
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_HOME = 0x24
VK_END = 0x23
VK_RIGHT = 0x27
VK_A = 0x41
VK_C = 0x43
_SCAN_RIGHT = 0x4D
_SCAN_HOME = 0x47
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13
# scan codes: Enter 0x1C, Tab 0x0F, Insert 0x52, F1 0x3B
_SCAN_ENTER = 0x1C
_SCAN_TAB = 0x0F
_SCAN_INSERT = 0x52
_SCAN_F1 = 0x3B
# Evita Enter duplicado (vazamento do terminal + keybd_event) em sequência rápida
_LAST_ENTER_MONO = 0.0
_ENTER_COOLDOWN_S = 0.6
_RE_COD_PROCEDIMENTO = re.compile(r"\d{2}\.\d{2}\.\d{2}\.\d{3}-\d")


def _texto_indica_tela_procedimentos(texto: str) -> bool:
    """True se o texto do campo/clipboard indica tela PROCEDIMENTOS REALIZADOS."""
    t = (texto or "").strip()
    if not t:
        return False
    upper = t.upper()
    if "PROCEDIMENTOS REALIZADOS" in upper:
        return True
    if "COD.PROCEDIMENTO" in upper or "CID PRINC" in upper:
        return True
    # Ex.: 15.12.19.753-0 (campo Cod.Procedimento)
    return bool(_RE_COD_PROCEDIMENTO.search(t))


def ativar_hwnd(hwnd: int) -> bool:
    """
    Força a janela para o primeiro plano mesmo se o foco estiver no Cursor/terminal.
    Usa AttachThreadInput para contornar a restrição do Windows a SetForegroundWindow.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE = 9
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        if user32.GetForegroundWindow() == hwnd:
            return True

        fg = user32.GetForegroundWindow()
        current_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)

        attached_fg = False
        attached_tg = False
        try:
            if fg_tid and fg_tid != current_tid:
                attached_fg = bool(user32.AttachThreadInput(current_tid, fg_tid, True))
            if target_tid and target_tid != current_tid and target_tid != fg_tid:
                attached_tg = bool(user32.AttachThreadInput(current_tid, target_tid, True))

            user32.BringWindowToTop(hwnd)
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass
        finally:
            if attached_tg:
                user32.AttachThreadInput(current_tid, target_tid, False)
            if attached_fg:
                user32.AttachThreadInput(current_tid, fg_tid, False)

        time.sleep(0.12)
        # Mesmo se o Windows ainda não reportar o hwnd como FG, o Enter
        # tenta de novo / usa PostMessage — não falhar só pelo foco.
        return True
    except Exception:
        return False


def _lparam_tecla(scan: int, *, key_up: bool) -> int:
    """Monta lParam de WM_KEYDOWN/KEYUP com o scan code."""
    base = (scan & 0xFF) << 16 | 1
    if key_up:
        return base | 0xC0000000
    return base


def aguardar_enter_solto(timeout_s: float | None = None) -> None:
    """
    Espera o Enter do input() no terminal ser solto antes de focar o APAC.
    Sem isso, o keyup/Enter vaza e pula campos (ex.: CNES SOLICITANTE).
    Timeouts/settles vêm do perfil apac.velocidade quando omitidos.
    Se Enter ja esta solto, so aplica enter_solto_tail (sem loop ate timeout).
    """
    if timeout_s is None:
        timeout_s = timing_apac("enter_solto_timeout", 2.0)
    settle = timing_apac("enter_solto_settle", 0.18)
    tail = timing_apac("enter_solto_tail", 0.2)
    user32 = ctypes.windll.user32
    if not bool(user32.GetAsyncKeyState(VK_RETURN) & 0x8000):
        time.sleep(tail)
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pressed = bool(user32.GetAsyncKeyState(VK_RETURN) & 0x8000)
        if not pressed:
            time.sleep(settle)
            if not bool(user32.GetAsyncKeyState(VK_RETURN) & 0x8000):
                return
        time.sleep(min(0.04, settle))
    time.sleep(tail)


def enviar_tecla_hwnd(hwnd: int, vk: int, scan: int, *, nome: str = "tecla") -> None:
    """
    Envia uma tecla para a janela do APAC sem depender do usuário manter o foco.
    1) Espera Enter do terminal solto; força primeiro plano
    2) Se em primeiro plano: keybd_event (Windows Terminal)
    3) Senão: PostMessage na janela (fallback)
    """
    user32 = ctypes.windll.user32
    aguardar_enter_solto()
    ativar_hwnd(hwnd)
    time.sleep(timing_apac("pos_tecla_foco", 0.12))
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        user32.keybd_event(vk, scan, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(vk, scan, KEYEVENTF_KEYUP, 0)
        return

    log.warning(
        "APAC sem primeiro plano após forçar foco; enviando %s via PostMessage.",
        nome,
    )
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, _lparam_tecla(scan, key_up=False))
    user32.PostMessageW(hwnd, WM_KEYUP, vk, _lparam_tecla(scan, key_up=True))


def enviar_enter_hwnd(hwnd: int) -> None:
    """Envia Enter para a janela do APAC (com cooldown anti-duplicata)."""
    global _LAST_ENTER_MONO
    agora = time.monotonic()
    espera = _ENTER_COOLDOWN_S - (agora - _LAST_ENTER_MONO)
    if espera > 0:
        time.sleep(espera)
    # Garante que nenhum Enter do terminal ainda está pressionado
    curto = timing_apac("enter_solto_timeout_curto", 1.0)
    aguardar_enter_solto(timeout_s=curto)
    enviar_tecla_hwnd(hwnd, VK_RETURN, _SCAN_ENTER, nome="Enter")
    _LAST_ENTER_MONO = time.monotonic()
    # Espera o keyup assentar — reduz Enter vazado logo após o envio
    time.sleep(timing_apac("enter_solto_tail", 0.2))
    aguardar_enter_solto(timeout_s=curto)


def enviar_tab_hwnd(hwnd: int) -> None:
    """Envia Tab para a janela do APAC (avança campo sem validar tela)."""
    aguardar_enter_solto(timeout_s=timing_apac("enter_solto_timeout_curto", 1.0))
    enviar_tecla_hwnd(hwnd, VK_TAB, _SCAN_TAB, nome="Tab")
    time.sleep(timing_apac("pos_home", 0.1))


def enviar_f1_hwnd(hwnd: int) -> None:
    """Envia F1 (ajuda/lista de opcoes) para a janela do APAC."""
    aguardar_enter_solto(timeout_s=timing_apac("enter_solto_timeout_curto", 1.0))
    enviar_tecla_hwnd(hwnd, VK_F1, _SCAN_F1, nome="F1")
    time.sleep(timing_apac("pos_home", 0.1))


def enviar_shift_tab_hwnd(hwnd: int) -> None:
    """Envia Shift+Tab (volta um campo) com foco no APAC."""
    user32 = ctypes.windll.user32
    aguardar_enter_solto(timeout_s=timing_apac("enter_solto_timeout_curto", 1.0))
    ativar_hwnd(hwnd)
    time.sleep(timing_apac("pos_home", 0.1))
    user32.keybd_event(VK_SHIFT, 0, 0, 0)
    time.sleep(0.02)
    enviar_tecla_hwnd(hwnd, VK_TAB, _SCAN_TAB, nome="Shift+Tab")
    user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(timing_apac("enter_solto_tail", 0.2))


def _texto_parece_municipio_ibge(texto: str) -> bool:
    """Ex.: '211130 / SAO LUIS' (codigo IBGE + cidade) — nao e RACA/ETNIA."""
    t = (texto or "").strip().upper()
    if not t:
        return False
    return bool(re.match(r"^\d{6,7}\s*/\s*[A-ZÁÉÍÓÚÃÕÇ ]", t))


def _texto_parece_codigo_raca(texto: str) -> bool:
    """Codigo de raca/etnia tipico: 01..05 ou 1..5 (1-2 digitos)."""
    t = (texto or "").strip()
    if not t:
        return False
    return bool(re.fullmatch(r"0?[1-5]", t))


def _texto_parece_campo_errado_para_raca(texto: str) -> bool:
    """True se o valor claramente nao e ETNIA/RACA (telefone, email, nome, etc.)."""
    t = (texto or "").strip()
    if not t:
        return False
    if _texto_parece_municipio_ibge(t):
        return True
    if _texto_parece_codigo_raca(t):
        return False
    # Telefone / DDD+numero
    digitos = "".join(ch for ch in t if ch.isdigit())
    if len(digitos) >= 8:
        return True
    if "@" in t or "HTTP" in t.upper():
        return True
    # Nome / texto longo
    letras = sum(1 for ch in t if ch.isalpha())
    if letras >= 6:
        return True
    return False


def enviar_insert_hwnd(hwnd: int) -> None:
    """Envia Insert para a janela do APAC (inclusão na lista)."""
    enviar_tecla_hwnd(hwnd, VK_INSERT, _SCAN_INSERT, nome="Insert")


def enviar_atalho_hwnd(hwnd: int, vk_mod: int, vk_key: int, *, nome: str) -> None:
    """Envia atalho (ex.: Ctrl+A) com foco no APAC."""
    user32 = ctypes.windll.user32
    aguardar_enter_solto()
    ativar_hwnd(hwnd)
    time.sleep(0.12)
    if user32.GetForegroundWindow() != hwnd:
        ativar_hwnd(hwnd)
        time.sleep(0.12)
    user32.keybd_event(vk_mod, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(vk_key, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(vk_mod, 0, KEYEVENTF_KEYUP, 0)
    log.debug("Atalho APAC: %s", nome)


def limpar_clipboard() -> None:
    user32 = ctypes.windll.user32
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
    finally:
        user32.CloseClipboard()


def ler_clipboard_texto() -> str:
    """Lê texto Unicode da área de transferência (Windows)."""
    # 1) win32 API com restype 64-bit (sem isso GlobalLock trunca e crasha)
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        if not user32.OpenClipboard(None):
            raise OSError("OpenClipboard falhou")
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                size = int(kernel32.GlobalSize(handle) or 0)
                # UTF-16: tamanho em bytes; deixa margem se GlobalSize=0
                nchars = max((size // 2) - 1, 0) if size else 4096
                return ctypes.wstring_at(ptr, nchars).split("\x00", 1)[0]
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        log.debug("Clipboard via ctypes falhou: %s — tentando PowerShell.", exc)

    # 2) Fallback PowerShell (evita access violation)
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "try { Get-Clipboard -Raw } catch { '' }",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        return (r.stdout or "").rstrip("\r\n")
    except Exception as exc:
        log.warning("Falha ao ler clipboard: %s", exc)
        return ""


def _selecionar_campo_home_shift_end(hwnd: int) -> None:
    """Seleciona o conteudo do campo: Home depois Shift+End (fallback ao Ctrl+A)."""
    user32 = ctypes.windll.user32
    aguardar_enter_solto()
    ativar_hwnd(hwnd)
    time.sleep(0.1)
    user32.keybd_event(VK_HOME, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_HOME, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_SHIFT, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_END, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(VK_END, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)


def _cancelar_selecao_campo(hwnd: int) -> None:
    """
    Apos Ctrl+C o texto fica selecionado; Tab com selecao no Magnético pode
    comportar-se mal.

    Usa Home (nao Right): em conhost/APAC, Right no fim do campo pode ir ao
    proximo campo e causar avanço duplo (Tab em seguida = pula tela).
    """
    enviar_tecla_hwnd(hwnd, VK_HOME, _SCAN_HOME, nome="Home")
    time.sleep(0.08)


def ler_campo_focado_via_clipboard(hwnd: int) -> str:
    """
    Com foco no campo atual do APAC: Home/Shift+End + Ctrl+C (preferencial).
    Ctrl+A só na 2ª tentativa — em alguns consoles Ctrl+A tem efeito colateral.
    """
    for tentativa in range(2):
        ativar_hwnd(hwnd)
        time.sleep(0.15)
        limpar_clipboard()
        time.sleep(0.15)
        if tentativa == 0:
            _selecionar_campo_home_shift_end(hwnd)
        else:
            enviar_atalho_hwnd(hwnd, VK_CONTROL, VK_A, nome="Ctrl+A")
        time.sleep(0.22)
        enviar_atalho_hwnd(hwnd, VK_CONTROL, VK_C, nome="Ctrl+C")
        time.sleep(0.45)
        texto = (ler_clipboard_texto() or "").strip()
        if texto:
            if tentativa > 0:
                log.info(
                    "Clipboard ok na tentativa %s (selecao alternativa).",
                    tentativa + 1,
                )
            return texto
        log.debug("Clipboard vazio na tentativa %s/2.", tentativa + 1)
        time.sleep(0.3)
    return ""


def enviar_texto_hwnd(hwnd: int, texto: str) -> None:
    """
    Digita texto no APAC via keybd_event (força foco; nao usa pyautogui.write).
    Funciona apos s no terminal — espera Enter solto antes de ativar.
    Intervalos por tecla vêm de apac.velocidade (char_down / char_up).
    """
    user32 = ctypes.windll.user32
    VK_SHIFT = 0x10
    char_down = timing_apac("char_down", 0.035)
    char_up = timing_apac("char_up", 0.045)
    aguardar_enter_solto()
    ativar_hwnd(hwnd)
    time.sleep(0.15)
    if user32.GetForegroundWindow() != hwnd:
        ativar_hwnd(hwnd)
        time.sleep(0.15)

    for ch in texto:
        mapped = user32.VkKeyScanW(ord(ch))
        if mapped == -1 or mapped == 0xFFFFFFFF:
            log.warning("Caractere sem VK: %r — ignorado", ch)
            continue
        vk = mapped & 0xFF
        shift = (mapped >> 8) & 0xFF
        if shift & 1:
            user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(char_down)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        if shift & 1:
            user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(char_up)


def retangulo_hwnd(hwnd: int) -> tuple[int, int, int, int]:
    """Retorna (left, top, right, bottom) da janela."""
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ApacBlockedError(f"GetWindowRect falhou para hwnd={hwnd}")
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _titulo_excluido(titulo: str) -> bool:
    t = (titulo or "").lower()
    return any(x in t for x in TITULO_EXCLUSOES)


def hwnds_janela_apac(titulo_needle: str) -> list[int]:
    """
    Janelas candidatas do APAC Magnético.
    Usa o processo APAC.exe (console) + janela do Windows Terminal/conhost com título adequado.
    Evita falsos positivos (Cursor, Chrome, planilha, etc.).
    """
    if not pids_do_processo(APAC_PROCESS_NAME):
        return []

    user32 = ctypes.windll.user32
    needle = (titulo_needle or "APAC").lower()
    apac_pids = set(pids_do_processo(APAC_PROCESS_NAME))
    nome_cache: dict[int, str] = {}
    found: list[tuple[int, int]] = []  # (score, hwnd)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):  # type: ignore[misc]
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = classe_hwnd(hwnd)
        if cls == "PseudoConsoleWindow":
            return True
        titulo = titulo_hwnd(hwnd)
        if not titulo or _titulo_excluido(titulo):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid_i = int(pid.value)
        if pid_i not in nome_cache:
            nome_cache[pid_i] = _nome_processo_pid(pid_i)
        proc = nome_cache[pid_i]

        score = 0
        if pid_i in apac_pids:
            score = 100
        elif proc in HOST_WINDOW_PROCESS_NAMES and needle in titulo.lower():
            score = 80
        elif needle in titulo.lower() and "magnet" in titulo.lower():
            score = 60
        else:
            return True

        found.append((score, int(hwnd)))
        return True

    user32.EnumWindows(_enum, 0)
    found.sort(key=lambda x: (-x[0], x[1]))
    return [hwnd for _, hwnd in found]


class ApacBlockedError(Exception):
    """Execução live bloqueada por mapeamento incompleto ou política de segurança."""


class DadosIncompletosError(ApacBlockedError):
    """
    Dados obrigatórios ausentes/inválidos no BIODATA (ou paciente não resolvido).
    No lote open-apac: marcar AGUARDANDO_REVISAO e seguir para o próximo.
    """

    def __init__(self, message: str, motivo: Optional[str] = None):
        super().__init__(message)
        self.motivo = motivo or message


class ApacInterruptedError(Exception):
    """Interrupção durante passo crítico (ex.: salvamento)."""

    def __init__(self, message: str, durante_salvamento: bool = False):
        super().__init__(message)
        self.durante_salvamento = durante_salvamento


def decidir_acao_equipe(campo: CampoApac) -> str:
    """
    Decisao pura apos CNS: o que fazer no passo Equipe.
    - tab: foco em EQUIPE → 1 Tab
    - ja_pulada: Magnético ja pulou (SERVICO/CLASSIFICACAO)
    - avancar: ainda atras (ex. CNS) → Tab e rele
    """
    if campo == CampoApac.EQUIPE:
        return "tab"
    if campo in (CampoApac.SERVICO, CampoApac.CLASSIFICACAO):
        return "ja_pulada"
    return "avancar"


def decidir_acao_servico(campo: CampoApac) -> str:
    """
    Decisao pura no passo Servico.
    - tab: foco em SERVICO → 1 Tab (aceitar)
    - ja_ok: ja em CLASSIFICACAO (servico ultrapassado)
    - avancar: atras → Tab e rele
    """
    if campo == CampoApac.SERVICO:
        return "tab"
    if campo == CampoApac.CLASSIFICACAO:
        return "ja_ok"
    return "avancar"


def decidir_acao_classificacao(campo: CampoApac) -> str:
    """
    Decisao pura no passo Classificacao.
    - tab: foco em CLASSIFICACAO → aceitar (Enter no Magnético; CID a seguir)
    - avancar: atras → Tab e rele
    """
    if campo == CampoApac.CLASSIFICACAO:
        return "tab"
    return "avancar"


@dataclass
class ApacStepResult:
    ok: bool
    message: str
    parado_antes_salvar: bool = False


def resolver_caminho_exe(
    cfg: AppConfig,
    *,
    drive_root: Path | None = None,
) -> Path:
    """
    Resolve o caminho do APAC.exe.
    Ordem: config.caminho_exe → C:\\APAC\\APAC.exe → pastas C:\\*APAC*\\APAC.exe (depth<=2).
    """
    apac = cfg.apac or {}
    configurado = (apac.get("caminho_exe") or "").strip()
    if configurado:
        p = Path(configurado)
        if p.is_file():
            return p.resolve()

    if DEFAULT_APAC_EXE.is_file():
        return DEFAULT_APAC_EXE.resolve()

    root = drive_root or Path("C:/")
    try:
        filhos = sorted(root.iterdir(), key=lambda x: x.name.lower())
    except OSError as exc:
        raise ApacBlockedError(
            f"Não foi possível listar {root} para achar APAC.exe: {exc}. "
            "Defina apac.caminho_exe no config.json."
        ) from exc

    for pasta in filhos:
        try:
            if not pasta.is_dir():
                continue
        except OSError:
            continue
        if "apac" not in pasta.name.lower():
            continue
        direto = pasta / "APAC.exe"
        if direto.is_file():
            return direto.resolve()
        try:
            for filho in pasta.iterdir():
                if filho.is_file() and filho.name.lower() == "apac.exe":
                    return filho.resolve()
                if filho.is_dir():
                    nested = filho / "APAC.exe"
                    if nested.is_file():
                        return nested.resolve()
        except OSError:
            continue

    raise ApacBlockedError(
        "APAC.exe não encontrado. Defina apac.caminho_exe no config.json "
        r"(padrão esperado: C:\APAC\APAC.exe)."
    )


class ApacAutomator:
    """
    Envia teclas ao APAC Magnético via PyAutoGUI.
    Passos vêm apenas da configuração — não inventa sequência SUS/APAC.
    """

    def __init__(
        self,
        cfg: AppConfig,
        *,
        dry_run: bool = True,
        confirm_fn: Optional[Callable[[str], bool]] = None,
    ):
        self.cfg = cfg
        self.dry_run = dry_run
        self.confirm_fn = confirm_fn or _confirm_terminal
        self._velocidade = aplicar_velocidade_apac(
            str(cfg.apac.get("velocidade") or "seguro")
        )
        log.info("APAC velocidade=%s", self._velocidade)
        self._pyautogui = None
        self._ensure_feito = False
        self._nav_inicial_feita = False
        self._insert_inclusao_feito = False
        self._numero_preenchido = False
        self._cnes_preenchido = False
        self._validade_preenchida = False
        self._tipo_nacionalidade_feito = False
        self._prontuario_sem_cpf_feito = False
        self._cpf_preenchido = False
        self._situacao_rua_feita = False
        self._nome_aceito = False
        self._cpf_preencheu_nome = False  # NOME veio do APAC via CPF (clipboard ok)
        self._nome_mae_aceito = False
        self._nome_responsavel_aceito = False
        self._cep_aceito = False
        self._logradouro_aceito = False
        self._endereco_aceito = False
        self._numero_end_aceito = False
        self._complemento_aceito = False
        self._bairro_aceito = False
        self._telefone_ddd_aceito = False
        self._telefone_num_aceito = False
        self._email_aceito = False
        self._nascimento_aceito = False
        self._sexo_aceito = False
        self._raca_aceito = False
        self._procedimentos_tela_ok = False
        self._cod_procedimento_preenchido = False
        self._cbo_preenchido = False
        self._qtd_procedimento_preenchida = False
        self._cns_executante_preenchido = False
        self._equipe_pulada = False
        self._servico_aceito = False
        self._classificacao_aceita = False
        self._motivo_saida_preenchido = False
        self._data_alta_preenchida = False
        self._cid_complementares_ok = False
        self._solicitacao_ok = False
        self._proc: Optional[subprocess.Popen] = None
        self._biodata_connector = None

    def _reiniciar_flags_paciente(self) -> None:
        """Zera flags de um paciente para permitir Insert + preenchimento do proximo."""
        self._insert_inclusao_feito = False
        self._numero_preenchido = False
        self._cnes_preenchido = False
        self._validade_preenchida = False
        self._tipo_nacionalidade_feito = False
        self._prontuario_sem_cpf_feito = False
        self._cpf_preenchido = False
        self._situacao_rua_feita = False
        self._nome_aceito = False
        self._cpf_preencheu_nome = False
        self._nome_mae_aceito = False
        self._nome_responsavel_aceito = False
        self._cep_aceito = False
        self._logradouro_aceito = False
        self._endereco_aceito = False
        self._numero_end_aceito = False
        self._complemento_aceito = False
        self._bairro_aceito = False
        self._telefone_ddd_aceito = False
        self._telefone_num_aceito = False
        self._email_aceito = False
        self._nascimento_aceito = False
        self._sexo_aceito = False
        self._raca_aceito = False
        self._procedimentos_tela_ok = False
        self._cod_procedimento_preenchido = False
        self._cbo_preenchido = False
        self._qtd_procedimento_preenchida = False
        self._cns_executante_preenchido = False
        self._equipe_pulada = False
        self._servico_aceito = False
        self._classificacao_aceita = False
        self._motivo_saida_preenchido = False
        self._data_alta_preenchida = False
        self._cid_complementares_ok = False
        self._solicitacao_ok = False

    def _pg(self):
        if self._pyautogui is None:
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = float(self.cfg.timeouts.get("apac_pause_s", 0.5))
            self._pyautogui = pyautogui
        return self._pyautogui

    def assert_live_allowed(self) -> None:
        apac = self.cfg.apac
        passos = apac.get("passos") or []
        if not passos:
            raise ApacBlockedError(
                "apac.passos vazio — execução live bloqueada. Mapeie a sequência "
                "de telas/teclas na configuração após testar manualmente."
            )
        minimos = apac.get("passos_minimos_para_live") or []
        nomes = {p.get("id") or p.get("acao") for p in passos if isinstance(p, dict)}
        faltando = [m for m in minimos if m not in nomes]
        if faltando:
            raise ApacBlockedError(
                "Passos mínimos ausentes para live: " + ", ".join(faltando)
            )
        if not apac.get("titulo_janela"):
            raise ApacBlockedError("apac.titulo_janela não configurado.")

    def _titulo_busca(self) -> str:
        return str(self.cfg.apac.get("titulo_janela") or "APAC MAGNETICO")

    def _pids_apac(self) -> list[int]:
        return pids_do_processo(APAC_PROCESS_NAME)

    def _hwnds_apac(self) -> list[int]:
        return hwnds_janela_apac(self._titulo_busca())

    def _processo_rodando(self) -> bool:
        return bool(self._pids_apac())

    def _janela_encontrada(self) -> bool:
        try:
            return len(self._hwnds_apac()) > 0
        except Exception:
            return False

    def focus_window(self) -> bool:
        titulo = self._titulo_busca()
        if self.dry_run:
            log.info("[dry-run] foco na janela do APAC Magnético")
            return True

        hwnds = self._hwnds_apac()
        if not hwnds:
            log.error(
                "Janela do APAC Magnético não encontrada "
                "(processo APAC.exe + título contendo '%s' no Terminal).",
                titulo,
            )
            return False

        alvo = hwnds[0]
        if ativar_hwnd(alvo):
            time.sleep(0.3)
            return True

        if not self.confirm_fn(
            f"Não foi possível ativar a janela APAC ('{titulo_hwnd(alvo)}'). "
            "Ative manualmente e confirme para continuar (s/n): "
        ):
            return False
        time.sleep(0.3)
        return True

    def _iniciar_exe(self, exe: Path) -> None:
        """
        Abre o APAC.
        Com apac.usar_conhost=true (padrao): conhost classico (buffer legivel).
        Com false: start via cmd (pode cair no Windows Terminal).
        """
        usar_conhost = self._flag_apac_bool("usar_conhost", True)
        if usar_conhost:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            conhost = Path(system_root) / "System32" / "conhost.exe"
            if not conhost.is_file():
                raise ApacBlockedError(f"conhost.exe nao encontrado em {conhost}")
            log.info("Iniciando APAC via conhost: %s -- %s", conhost, exe)
            # CREATE_NEW_CONSOLE: janela propria, destacada do terminal do Cursor
            self._proc = subprocess.Popen(
                [str(conhost), "--", str(exe)],
                cwd=str(exe.parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
            )
            return

        # Fallback legado (WT / padrao do usuario)
        self._proc = subprocess.Popen(
            ["cmd", "/c", "start", "", "/D", str(exe.parent), exe.name],
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def ensure_running(self) -> bool:
        """Garante que o APAC.exe está rodando (inicia se necessário) e foca a janela."""
        if self.dry_run:
            try:
                exe = resolver_caminho_exe(self.cfg)
                log.info("[dry-run] abriria APAC em %s se necessário", exe)
            except ApacBlockedError as exc:
                log.info("[dry-run] %s", exc)
            return True

        if self._ensure_feito and self._janela_encontrada():
            return self.focus_window()

        if self._processo_rodando() and self._janela_encontrada():
            self._ensure_feito = True
            return self.focus_window()

        if self._processo_rodando() and not self._janela_encontrada():
            timeout_rapido = min(10.0, float(self.cfg.apac.get("timeout_abrir_s") or 30))
            deadline = time.time() + timeout_rapido
            while time.time() < deadline:
                if self._janela_encontrada():
                    self._ensure_feito = True
                    return self.focus_window()
                time.sleep(0.5)

        exe = resolver_caminho_exe(self.cfg)
        # Encerra zombie preso ao PseudoConsole sem janela útil
        if self._processo_rodando() and not self._janela_encontrada():
            log.warning("APAC.exe sem janela útil; encerrando processo residual e reiniciando.")
            subprocess.run(
                ["taskkill", "/IM", APAC_PROCESS_NAME, "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1)

        log.info("APAC.exe não está aberto; iniciando %s", exe)
        try:
            self._iniciar_exe(exe)
        except OSError as exc:
            raise ApacBlockedError(f"Falha ao iniciar {exe}: {exc}") from exc

        timeout = float(self.cfg.apac.get("timeout_abrir_s") or 30)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._processo_rodando() and self._janela_encontrada():
                self._ensure_feito = True
                log.info(
                    "APAC em execução; janela detectada: %s",
                    titulo_hwnd(self._hwnds_apac()[0]),
                )
                return self.focus_window()
            time.sleep(0.5)

        if self._processo_rodando():
            raise ApacBlockedError(
                f"APAC.exe está em execução ({exe}), mas a janela "
                f"'{self._titulo_busca()}' não apareceu em {timeout:.0f}s. "
                "Confira se o Windows Terminal abriu a aba APAC MAGNETICO."
            )
        raise ApacBlockedError(
            f"Falha ao manter APAC.exe aberto ({exe}) em {timeout:.0f}s."
        )

    def _hwnd_apac_ativo(self) -> int:
        hwnds = self._hwnds_apac()
        if not hwnds:
            raise ApacBlockedError(
                "Janela APAC MAGNETICO não encontrada para navegação."
            )
        return hwnds[0]

    def _ativar_janela_apac(self, *, clicar_centro: bool) -> int:
        """
        Rouba o foco de volta para o APAC (mesmo após digitar s no Cursor).
        Espera Enter do terminal solto para nao vazar tecla e pular campos.
        Clique no centro só com menu fechado — com submenu aberto o clique fecha o menu.
        Retorna o hwnd ativo.
        """
        aguardar_enter_solto()
        hwnd = self._hwnd_apac_ativo()
        if not ativar_hwnd(hwnd):
            raise ApacBlockedError("Não foi possível ativar a janela do APAC.")
        time.sleep(0.2)
        if not clicar_centro:
            log.info("Foco APAC: forçado sem clique (preserva submenu)")
            return hwnd
        left, top, right, bottom = retangulo_hwnd(hwnd)
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        pg = self._pg()
        pg.click(cx, cy)
        time.sleep(0.2)
        # Após o clique, garantir de novo (click não deve deixar o Cursor na frente)
        ativar_hwnd(hwnd)
        log.info("Foco APAC: clique no centro (%s, %s)", cx, cy)
        return hwnd

    def _ativar_e_clicar_centro(self) -> None:
        """Ativa a janela e clica no centro — necessário para o console no Windows Terminal."""
        self._ativar_janela_apac(clicar_centro=True)

    def _enviar_enter(self, hwnd: Optional[int] = None) -> None:
        """Envia Enter ao APAC mesmo se o foco estiver no terminal do Cursor."""
        alvo = hwnd or self._hwnd_apac_ativo()
        enviar_enter_hwnd(alvo)

    def _enviar_tab(self, hwnd: Optional[int] = None) -> None:
        """Envia Tab ao APAC (campos do paciente: próximo campo sem validar tela)."""
        alvo = hwnd or self._hwnd_apac_ativo()
        enviar_tab_hwnd(alvo)

    def _enviar_insert(self, hwnd: Optional[int] = None) -> None:
        """Envia Insert ao APAC mesmo se o foco estiver no terminal do Cursor."""
        alvo = hwnd or self._hwnd_apac_ativo()
        enviar_insert_hwnd(alvo)

    def _enviar_f1(self, hwnd: Optional[int] = None) -> None:
        """Envia F1 ao APAC (ajuda / 1a opcao do menu)."""
        alvo = hwnd or self._hwnd_apac_ativo()
        enviar_f1_hwnd(alvo)

    def _digitar_texto(
        self,
        texto: str,
        hwnd: Optional[int] = None,
        *,
        limpar_antes: bool = False,
    ) -> None:
        """
        Digita texto no APAC via keybd_event (força foco; aguarda Enter do terminal).
        limpar_antes ignorado — Delete/Home pulava campos no Magnético.
        """
        if limpar_antes:
            log.debug("limpar_antes ignorado (evita pular campo no APAC)")
        alvo = hwnd or self._hwnd_apac_ativo()
        enviar_texto_hwnd(alvo, texto)

    def _pausa(self, chave: str) -> None:
        """Sleep conforme apac.velocidade (seguro|rapido)."""
        time.sleep(timing_apac(chave))

    def _aguardar_avanco_campo(
        self,
        campo_antes: CampoApac,
        *,
        timeout_s: float | None = None,
    ) -> bool:
        """
        Apos Tab: poll ate o cursor sair de campo_antes (ou timeout).
        Retorna True se avancou; False se timeout / erro de buffer.
        """
        if timeout_s is None:
            timeout_s = timing_apac("pos_tab_apos_aceitar", 0.9)
        poll = 0.04
        deadline = time.time() + max(0.0, timeout_s)
        while time.time() < deadline:
            try:
                campo_agora, linha_agora, _cx = identificar_campo_cursor(
                    self._pids_apac()
                )
                if not campo_compativel(
                    campo_agora, campo_antes, linha=linha_agora
                ):
                    return True
            except ConsoleScreenError:
                return False
            time.sleep(poll)
        return False

    def _intervalo_nav_enter(self) -> float:
        """Pausa entre Enters da navegacao MENU → lista."""
        if "intervalo_enter_navegacao_s" in self.cfg.apac:
            return float(self.cfg.apac.get("intervalo_enter_navegacao_s") or 2.0)
        return timing_apac("nav_enter", 2.0)

    def _confirmar_nav(self) -> bool:
        """
        Confirmacao dos passos JA mapeados no open-apac.
        Padrao false = roda automatico. True = pede s em cada passo mapeado.
        Passos novos devem usar _pedir_s_novo_passo (sempre pergunta).
        """
        confirmar = self.cfg.apac.get("confirmar_navegacao_inicial", False)
        if isinstance(confirmar, str):
            return confirmar.strip().lower() in {"1", "true", "sim", "yes"}
        return bool(confirmar)

    def _pedir_s_novo_passo(self, prompt: str) -> None:
        """Sempre pede s — use em passos ainda nao estabilizados (seguranca)."""
        ok = self.confirm_fn(prompt)
        if not ok:
            raise ApacBlockedError(f"operador recusou passo novo: {prompt.strip()}")
        aguardar_enter_solto()

    def _flag_apac_bool(self, chave: str, default: bool = False) -> bool:
        val = self.cfg.apac.get(chave, default)
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "sim", "yes"}
        return bool(val)

    def _encerrar_apac_processo(self) -> None:
        """taskkill /IM APAC.exe /F e zera flags de sessao local."""
        subprocess.run(
            ["taskkill", "/IM", APAC_PROCESS_NAME, "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)
        self._ensure_feito = False
        self._nav_inicial_feita = False
        self._insert_inclusao_feito = False

    def garantir_sessao_inicial_limpa(self) -> None:
        """
        Se apac.reiniciar_se_ja_aberto (default True) e APAC.exe ja roda:
        encerra para reabrir no MENU via conhost (buffer legivel).
        """
        if not self._flag_apac_bool("reiniciar_se_ja_aberto", True):
            return
        if self.dry_run:
            log.info(
                "[dry-run] reiniciar_se_ja_aberto=true — encerraria APAC se aberto"
            )
            return
        if not self._processo_rodando():
            return
        log.info("APAC ja aberto — reiniciando para MENU PRINCIPAL (conhost)")
        self._encerrar_apac_processo()

    def ler_tela_console(self) -> str:
        """Le o buffer da tela do APAC.exe (exige conhost)."""
        if self.dry_run:
            return ""
        try:
            return ler_buffer_apac(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(str(exc)) from exc

    def classificar_tela_atual(self) -> tuple[TelaApac, str]:
        texto = self.ler_tela_console()
        tela = classificar_tela(texto)
        log.info(
            "Tela APAC classificada: %s (%s)",
            tela.value,
            preview_tela(texto, 120),
        )
        return tela, texto

    def exigir_tela(self, esperada: TelaApac, *, passo: str) -> str:
        """
        Le o buffer, classifica e aborta se nao for a tela esperada.
        Cair em PROCEDIMENTOS sem esperar essa tela ainda aborta.
        """
        if self.dry_run:
            log.info("[dry-run] exigir_tela %s no passo %s", esperada.value, passo)
            return ""
        tela, texto = self.classificar_tela_atual()
        if (
            tela == TelaApac.PROCEDIMENTOS
            and esperada != TelaApac.PROCEDIMENTOS
        ):
            raise ApacBlockedError(
                f"Passo '{passo}': tela e PROCEDIMENTOS REALIZADOS "
                f"(preview: {preview_tela(texto)!r}). Pare — nao continuar."
            )
        if tela != esperada:
            raise ApacBlockedError(
                f"Passo '{passo}': esperava tela {esperada.value}, "
                f"encontrou {tela.value} (preview: {preview_tela(texto)!r}). "
                "Pare — volte a tela correta ou reinicie o APAC."
            )
        return texto

    def exigir_campo(
        self,
        esperado: CampoApac,
        *,
        passo: str,
        tela: TelaApac = TelaApac.IDENTIFICACAO,
    ) -> str:
        """
        Exige a tela indicada e que a linha do cursor seja o campo esperado.
        Sem recuperacao (Shift+Tab). Retorna a linha lida.
        """
        if self.dry_run:
            log.info(
                "[dry-run] exigir_campo %s (tela %s) no passo %s",
                esperado.value,
                tela.value,
                passo,
            )
            return ""
        self.exigir_tela(tela, passo=passo)
        try:
            campo, linha, cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"Passo '{passo}': falha ao ler campo no cursor: {exc}"
            ) from exc
        if not campo_compativel(campo, esperado, linha=linha):
            raise ApacBlockedError(
                f"Passo '{passo}': esperava campo {esperado.value}, "
                f"encontrou {campo.value} (linha: {linha[:80]!r}). "
                "Pare — ajuste o foco ou rode dump-apac-screen e calibra os marcadores."
            )
        log.info(
            "Campo OK passo=%s esperado=%s lido=%s cx=%s linha=%r",
            passo,
            esperado.value,
            campo.value,
            cx,
            linha[:60],
        )
        return linha

    def exigir_campo_nao_contato(self, *, passo: str) -> None:
        """
        Gate negativo no cabecalho: aborta se o cursor ja estiver em
        telefone/municipio/etnia (fora da ordem inicial).
        """
        if self.dry_run:
            return
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError:
            return
        proibidos = {
            CampoApac.TELEFONE,
            CampoApac.EMAIL,
            CampoApac.MUNICIPIO,
            CampoApac.ETNIA_RACA,
            CampoApac.BAIRRO,
            CampoApac.COMPLEMENTO,
        }
        if campo in proibidos:
            raise ApacBlockedError(
                f"Passo '{passo}': foco em {campo.value} "
                f"(linha: {linha[:80]!r}) — esperado cabecalho/identificacao inicial. "
                "Pare e ajuste o foco."
            )

    def preencher_numero_apac(self, lanc: Lancamento) -> None:
        """
        Digita numeracao_apac no campo NUMERO e Enter para abrir o formulario
        (foco em NUMERO DA APAC ANTERIOR). Enter do formulario (APAC ANTERIOR)
        fica em preencher_cnes_unidade — unico Enter "de campo" la.
        """
        if self._numero_preenchido:
            return

        numero = lanc.numeracao_apac
        if self.dry_run:
            log.info(
                "[dry-run] NUMERO — %s → %s + Enter (abre form)",
                lanc.paciente_nome,
                numero,
            )
            self._numero_preenchido = True
            return

        confirmar = self._confirmar_nav()

        if confirmar:
            ok = self.confirm_fn(
                f"NUMERO — {lanc.paciente_nome} — digite s para enviar {numero} "
                f"e ENTER (abre formulario): "
            )
            if not ok:
                raise ApacBlockedError(
                    f"operador recusou digitar NUMERO ({lanc.paciente_nome})"
                )

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando NUMERO %s (%s)", numero, lanc.paciente_nome)
        self._digitar_texto(numero, hwnd)
        self._pausa("pos_apos_digitar_numero")
        # Enter imediato apos digitar (sem 2o s) — evita Enter manual no meio e campo pulado
        log.info("Enter apos NUMERO — abre formulario (foco APAC ANTERIOR)")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        self._numero_preenchido = True
        log.info(
            "NUMERO ok — foco deve estar em CNES SOLICITANTE "
            "(nao enviar Enter de novo; so digitar o codigo)."
        )

    def preencher_cnes_unidade(self, lanc: Lancamento) -> None:
        """
        Apos NUMERO+Enter o foco ja esta em CNES SOLICITANTE (APAC ANTERIOR
        ja foi pulado — NAO enviar Enter de novo, senao pula o SOLICITANTE).

          1) s + digita cnes_solicitante (APAC foca EXECUTANTE sozinho; sem Enter)
          2) s + digita cnes_executante (sem Enter; para)
        """
        if self._cnes_preenchido:
            return

        fixos = self.cfg.dados_fixos
        cnes_sol = str(fixos.get("cnes_solicitante") or "").strip()
        cnes_exec = str(fixos.get("cnes_executante") or "").strip()
        if not cnes_sol or not cnes_exec:
            raise ApacBlockedError(
                "dados_fixos.cnes_solicitante e cnes_executante sao obrigatorios "
                "(valor por clinica/empresa; ex.: 6618839)."
            )

        if self.dry_run:
            log.info(
                "[dry-run] CNES — sol=%s; exec=%s (%s) — sem Enter",
                cnes_sol,
                cnes_exec,
                lanc.paciente_nome,
            )
            self._cnes_preenchido = True
            return

        confirmar = self._confirmar_nav()

        # 1) CNES SOLICITANTE (ja focado — nao dar Enter)
        if confirmar:
            ok = self.confirm_fn(
                f"1/2 Colar CNES SOLICITANTE {cnes_sol}? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou CNES SOLICITANTE")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("1/2 Digitando CNES SOLICITANTE %s (sem Enter)", cnes_sol)
        self._digitar_texto(cnes_sol, hwnd)
        self._pausa("pos_digitar_cnes")

        # 2) CNES EXECUTANTE
        if confirmar:
            ok = self.confirm_fn(
                f"2/2 Colar CNES EXECUTANTE {cnes_exec}? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou CNES EXECUTANTE")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("2/2 Digitando CNES EXECUTANTE %s (sem Enter)", cnes_exec)
        self._digitar_texto(cnes_exec, hwnd)
        self._pausa("pos_digitar_curto")

        self._cnes_preenchido = True
        log.info(
            "CNES ok (sol=%s exec=%s) — proximo: validade (mes anterior).",
            cnes_sol,
            cnes_exec,
        )

    def preencher_validade_mes_anterior(self) -> None:
        """
        Apos CNES EXECUTANTE o foco ja esta em INICIO DA VALIDADE.
          1) s + digita 1o dia do mes anterior (DDMMAAAA; sem Enter)
          2) s + digita ultimo dia do mes anterior (sem Enter; para)
        """
        if self._validade_preenchida:
            return

        inicio, fim = datas_validade_mes_anterior(
            fim_offset_meses=fim_offset_meses(self.cfg.modalidade)
        )
        inicio_legivel = f"{inicio[:2]}/{inicio[2:4]}/{inicio[4:]}"
        fim_legivel = f"{fim[:2]}/{fim[2:4]}/{fim[4:]}"

        if self.dry_run:
            log.info(
                "[dry-run] VALIDADE mes anterior — inicio=%s fim=%s",
                inicio_legivel,
                fim_legivel,
            )
            self._validade_preenchida = True
            return

        confirmar = self._confirmar_nav()

        if confirmar:
            ok = self.confirm_fn(
                f"1/2 INICIO DA VALIDADE {inicio_legivel}? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou INICIO DA VALIDADE")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("1/2 Digitando INICIO DA VALIDADE %s (sem Enter)", inicio)
        self._digitar_texto(inicio, hwnd)
        self._pausa("pos_enter_form")

        if confirmar:
            ok = self.confirm_fn(
                f"2/2 FIM DA VALIDADE {fim_legivel}? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou FIM DA VALIDADE")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("2/2 Digitando FIM DA VALIDADE %s (sem Enter)", fim)
        self._digitar_texto(fim, hwnd)
        self._pausa("pos_digitar_curto")

        self._validade_preenchida = True
        log.info(
            "VALIDADE ok (inicio=%s fim=%s) — proximo: TIPO DE APAC.",
            inicio_legivel,
            fim_legivel,
        )

    def preencher_tipo_e_nacionalidade(self) -> None:
        """
        Apos FIM DA VALIDADE o foco ja esta em TIPO DE APAC:
          1) s + digita tipo_apac (3 padrao / 1 glaucoma; sem Enter)
          2) s + Enter em NACIONALIDADE (nao digitar; pula)
        """
        if self._tipo_nacionalidade_feito:
            return

        tipo = "1" if self.cfg.modalidade == MODALIDADE_GLAUCOMA else "3"

        if self.dry_run:
            log.info(
                "[dry-run] TIPO DE APAC=%s + Enter NACIONALIDADE",
                tipo,
            )
            self._tipo_nacionalidade_feito = True
            return

        confirmar = self._confirmar_nav()

        if confirmar:
            ok = self.confirm_fn(
                f"1/2 TIPO DE APAC {tipo}? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou TIPO DE APAC")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("1/2 Digitando TIPO DE APAC %s (sem Enter)", tipo)
        self._digitar_texto(tipo, hwnd)
        self._pausa("pos_enter_form")

        if confirmar:
            ok = self.confirm_fn(
                "2/2 NACIONALIDADE — digite s para ENTER (pula; nao digitar): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Enter em NACIONALIDADE")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("2/2 Enter — NACIONALIDADE (pula)")
        self._enviar_enter(hwnd)
        self._pausa("pos_digitar_curto")

        self._tipo_nacionalidade_feito = True
        log.info(
            "TIPO=%s + NACIONALIDADE ok — proximo: prontuario / SEM CPF.",
            tipo,
        )

    def preencher_prontuario_e_sem_cpf(self) -> None:
        """
        Apos NACIONALIDADE o foco ja esta em No. PRONTUARIO:
          1) s + Enter (pula prontuario; nao preencher)
          2) s + digita n em SEM CPF (sem Enter; APAC avanca sozinho)
        """
        if self._prontuario_sem_cpf_feito:
            return

        if self.dry_run:
            log.info("[dry-run] Enter PRONTUARIO + digita n em SEM CPF")
            self._prontuario_sem_cpf_feito = True
            return

        confirmar = self._confirmar_nav()

        if confirmar:
            ok = self.confirm_fn(
                "1/2 No. PRONTUARIO — digite s para ENTER (pula; nao preencher): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Enter em PRONTUARIO")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("1/2 Enter — No. PRONTUARIO (pula)")
        self._enviar_enter(hwnd)
        self._pausa("pos_prontuario")

        if confirmar:
            ok = self.confirm_fn(
                "2/2 SEM CPF — digite s para digitar n (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar n em SEM CPF")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("2/2 Digitando SEM CPF = n (sem Enter)")
        self._digitar_texto("n", hwnd)
        self._pausa("pos_digitar_curto")

        self._prontuario_sem_cpf_feito = True
        log.info("PRONTUARIO + SEM CPF=n ok — proximo: CPF via BIODATA.")

    def preencher_cpf_apac(self, lanc: Lancamento, cpf_digitos: str) -> None:
        """
        Foco ja em CPF: digita somente digitos (sem Enter) para conferencia.
        """
        if self._cpf_preenchido:
            return

        if self.dry_run:
            log.info(
                "[dry-run] CPF — %s → %s****%s",
                lanc.paciente_nome,
                cpf_digitos[:3],
                cpf_digitos[-2:],
            )
            self._cpf_preenchido = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"Colar CPF de {lanc.paciente_nome} no APAC? digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou colar CPF no APAC")

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando CPF no APAC (%s digitos, sem Enter)", len(cpf_digitos))
        self._digitar_texto(cpf_digitos, hwnd)
        self._pausa("pos_digitar_curto")

        self._cpf_preenchido = True
        log.info("CPF digitado no APAC — proximo: SITUACAO DE RUA = n.")

    def preencher_situacao_rua(self) -> None:
        """
        Apos CPF o APAC ja foca em SITUACAO DE RUA:
        digita n (sem Enter — APAC avanca sozinho para NOME).
        """
        if self._situacao_rua_feita:
            return

        if self.dry_run:
            log.info("[dry-run] Digita n em SITUACAO DE RUA (sem Enter)")
            self._situacao_rua_feita = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "SITUACAO DE RUA — digite s para digitar n (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar n em SITUACAO DE RUA")

        # Pausa: APAC termina de avancar do CPF para SITUACAO DE RUA
        self._pausa("pos_raca_pre")
        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando SITUACAO DE RUA = n (sem Enter)")
        self._digitar_texto("n", hwnd)
        self._pausa("pos_digitar_curto")

        self._situacao_rua_feita = True
        log.info("SITUACAO DE RUA=n ok — proximo: verificar NOME (clipboard).")

    def _aceitar_campo_texto_se_preenchido(
        self,
        lanc: Lancamento,
        *,
        rotulo: str,
        flag_attr: str,
        max_chars: int = 120,
        vazio_aceita_tab: bool = False,
        vazio_digita: Optional[str] = None,
        aceitar_enter_se_origem: Optional[str] = None,
        aceitar_enter_se_cpf_preencheu: bool = False,
        marcar_cpf_preencheu_se_lido: bool = False,
        avancar_com_tab: bool = True,
    ) -> None:
        """
        Campo atual (foco): clipboard; se preenchido, Tab avança ao próximo.
        Se vazio: digita origem/vazio_digita — Magnético avança sozinho (NUNCA Tab apos digitar).
        Se clipboard vazio e CPF preencheu NOME: Tab. Ou Tab se vazio_aceita_tab.
        Com avancar_com_tab=False (ex.: ultimo campo RACA ja preenchido), nao envia Tab.
        """
        if getattr(self, flag_attr):
            return

        if self.dry_run:
            log.info(
                "[dry-run] Verificar %s via clipboard%s%s%s",
                rotulo,
                "; Tab se preenchido" if avancar_com_tab else "; sem Tab (parar no campo)",
                " (vazio tambem Tab)" if vazio_aceita_tab and avancar_com_tab else "",
                f" (vazio digita {vazio_digita!r})" if vazio_digita else "",
            )
            setattr(self, flag_attr, True)
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"Verificar {rotulo} de {lanc.paciente_nome} no APAC (clipboard)? digite s: "
            )
            if not ok:
                raise ApacBlockedError(f"operador recusou verificar {rotulo} no APAC")

        self._pausa("pre_campo")
        aguardar_enter_solto()
        campo_esp = _ROTULO_PARA_CAMPO.get(rotulo.upper())
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        # Preferir buffer no cursor — um read (gate + valor); clipboard so se falhar.
        texto = ""
        bruto = ""
        try:
            if campo_esp is not None:
                linha_gate = self.exigir_campo(campo_esp, passo=rotulo)
                bruto = (
                    extrair_valor_campo_linha(linha_gate, campo=campo_esp) or ""
                ).strip()
            else:
                self.exigir_tela(TelaApac.IDENTIFICACAO, passo=rotulo)
                bruto = (ler_valor_campo_cursor(self._pids_apac()) or "").strip()
            log.info(
                "Lendo campo %s via buffer (cursor, sem teclas): %r",
                rotulo,
                bruto[:80],
            )
            texto = self._normalizar_leitura_campo(rotulo, bruto)
        except ConsoleScreenError as exc:
            log.warning(
                "%s: buffer no cursor falhou (%s) — fallback clipboard.",
                rotulo,
                exc,
            )
            bruto = ler_campo_focado_via_clipboard(hwnd)
            _cancelar_selecao_campo(hwnd)
            log.info(
                "Lendo campo %s via clipboard (fallback): %r",
                rotulo,
                bruto[:80],
            )
            texto = self._normalizar_leitura_campo(rotulo, bruto)

        # Campos do APAC com linha “suja” no buffer: aceita valor isolado, sem barrar por len
        rotulo_u = rotulo.upper()
        if rotulo_u in {
            "CEP",
            "LOGRADOURO",
            "ENDERECO",
            "NUMERO",
            "DATA DE NASCIMENTO",
            "SEXO",
        }:
            if texto != (bruto or "").strip():
                log.info("%s no APAC normalizado da linha: %r", rotulo, texto)
        elif len(texto) > max_chars:
            log.warning(
                "Leitura com %s chars — %s duvidosa; pedindo revisao.",
                len(texto),
                rotulo,
            )
            raise ApacBlockedError(
                f"{rotulo}: leitura inconclusiva ({len(texto)} chars). "
                f"Confira o campo {rotulo} no APAC manualmente."
            )

        digitar_antes: Optional[str] = None
        origem_preview: Optional[str] = None
        if not texto:
            origem = None
            if aceitar_enter_se_origem:
                origem = self._valor_biodata_ou_refrescar(
                    lanc, aceitar_enter_se_origem, rotulo=rotulo
                )
            if origem:
                # Clipboard falhou (texto branco comum): sobrescreve com BIODATA
                digitar_antes = origem
                if rotulo_u == "CEP":
                    dig_cep = "".join(ch for ch in origem if ch.isdigit())
                    digitar_antes = dig_cep[:8] if len(dig_cep) >= 8 else None
                if digitar_antes:
                    origem_preview = digitar_antes
                    log.warning(
                        "%s: clipboard vazio, mas BIODATA tem '%s' — redigita "
                        "(Magnético avança sozinho, sem Tab).",
                        rotulo,
                        digitar_antes[:60],
                    )
                    motivo_avanco = "aceitar (redigitado; clipboard falhou)"
            if not digitar_antes:
                if aceitar_enter_se_cpf_preencheu and self._cpf_preencheu_nome:
                    log.warning(
                        "%s: clipboard vazio, mas CPF ja preencheu NOME — Tab para aceitar "
                        "(texto branco no Magnético).",
                        rotulo,
                    )
                    motivo_avanco = "aceitar (clipboard falhou; confia no CPF/APAC)"
                elif vazio_digita is not None:
                    if not str(vazio_digita).strip():
                        raise ApacBlockedError(
                            f"{rotulo} vazio no APAC e sem valor na origem (BIODATA) "
                            f"para '{lanc.paciente_nome}'."
                        )
                    digitar_antes = str(vazio_digita).strip()
                    log.info(
                        "%s vazio — digitando valor da origem: %s",
                        rotulo,
                        digitar_antes[:40],
                    )
                    motivo_avanco = "aceitar (digitado)"
                elif vazio_aceita_tab:
                    log.info("%s vazio — Tab para pular.", rotulo)
                    motivo_avanco = "pular (vazio)"
                else:
                    log.warning(
                        "%s vazio no APAC para %s — revisao.",
                        rotulo,
                        lanc.paciente_nome,
                    )
                    raise ApacBlockedError(
                        f"{rotulo} vazio no APAC para '{lanc.paciente_nome}'. "
                        "Preencha manualmente ou revise."
                    )
        else:
            log.info(
                "%s preenchido no APAC: %s — %s.",
                rotulo,
                texto[:80],
                "Tab para aceitar" if avancar_com_tab else "aceitar sem Tab (parar)",
            )
            motivo_avanco = "aceitar"
            if marcar_cpf_preencheu_se_lido:
                self._cpf_preencheu_nome = True

        if self._confirmar_nav():
            if digitar_antes:
                preview = digitar_antes[:60]
            elif texto:
                preview = texto[:60]
            elif origem_preview:
                preview = origem_preview[:60]
            else:
                preview = "(vazio)"
            if digitar_antes:
                acao = "digitar (sem Tab)"
            elif avancar_com_tab:
                acao = "TAB"
            else:
                acao = "confirmar sem Tab"
            ok = self.confirm_fn(
                f"{rotulo} '{preview}' — digite s para {acao} ({motivo_avanco}): "
            )
            if not ok:
                raise ApacBlockedError(f"operador recusou {acao} no {rotulo}")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        enviou_tab = False
        if digitar_antes:
            # So Home (sem Shift+End): selecionar com Shift+End adianta o foco no conhost
            enviar_tecla_hwnd(hwnd, VK_HOME, _SCAN_HOME, nome="Home")
            self._pausa("pos_home")
            a_digitar = digitar_antes[:max_chars]
            self._digitar_texto(a_digitar, hwnd)
            self._pausa("pos_digitar")
            log.info("%s: digitado (origem BIODATA/planilha).", rotulo)
            # Texto livre (NOME/MAE/end.) as vezes nao avanca sozinho — Tab se ainda no campo
            if avancar_com_tab and campo_esp is not None:
                try:
                    campo_agora, linha_agora, _cx = identificar_campo_cursor(
                        self._pids_apac()
                    )
                    if campo_compativel(
                        campo_agora, campo_esp, linha=linha_agora
                    ):
                        log.info(
                            "%s: ainda no mesmo campo apos digitar — Tab",
                            rotulo,
                        )
                        hwnd = self._ativar_janela_apac(clicar_centro=False)
                        self._enviar_tab(hwnd)
                        enviou_tab = True
                    else:
                        log.info(
                            "%s: Magnético ja avancou para %s",
                            rotulo,
                            campo_agora.value,
                        )
                except ConsoleScreenError as exc:
                    log.warning(
                        "%s: falha ao checar foco apos digitar (%s) — Tab",
                        rotulo,
                        exc,
                    )
                    hwnd = self._ativar_janela_apac(clicar_centro=False)
                    self._enviar_tab(hwnd)
                    enviou_tab = True
        elif avancar_com_tab:
            hwnd = self._ativar_janela_apac(clicar_centro=False)
            self._enviar_tab(hwnd)
            enviou_tab = True
        else:
            log.info("%s: aceito sem Tab — foco permanece no campo.", rotulo)
        if enviou_tab and campo_esp is not None:
            if not self._aguardar_avanco_campo(campo_esp):
                self._pausa("pos_tab_apos_aceitar")
        elif enviou_tab:
            self._pausa("pos_tab_apos_aceitar")
        else:
            self._pausa("pos_sem_tab")

        # Apos Tab: so buffer (nao clipboard) — se ja saiu da identificacao, para.
        if enviou_tab:
            self.exigir_tela(
                TelaApac.IDENTIFICACAO,
                passo=f"apos Tab em {rotulo}",
            )

        setattr(self, flag_attr, True)
        log.info(
            "%s: %s (%s)%s",
            rotulo,
            "Tab" if enviou_tab else "ok sem Tab",
            motivo_avanco,
            " — proximo campo." if enviou_tab else " — foco no campo.",
        )

    def _valor_biodata_ou_refrescar(
        self, lanc: Lancamento, attr: str, *, rotulo: str
    ) -> Optional[str]:
        """Le atributo do paciente; se ausente, refresca BIODATA (sessao aberta)."""
        pac = lanc.paciente
        val = getattr(pac, attr, None) if pac else None
        if val:
            return str(val).strip() or None
        conn = self._biodata_connector
        if conn is None:
            return None
        log.info("%s ausente no cache — reconsultando BIODATA...", rotulo)
        refrescar_paciente_biodata(conn, lanc)
        pac = lanc.paciente
        val = getattr(pac, attr, None) if pac else None
        return (str(val).strip() or None) if val else None

    def _aplicar_limite_nome_apac(self, nome: str, *, rotulo: str) -> str:
        """Abrevia sobrenomes se passar do limite do Magnético; loga se encurtou."""
        original = " ".join((nome or "").split())
        if not original:
            return ""
        completo = abreviar_nome_apac(original, max_len=10_000)
        curto = abreviar_nome_apac(original, APAC_MAX_NOME)
        if curto != completo:
            log.info(
                "%s: nome %r (%s chars) abreviado para %r (limite %s)",
                rotulo,
                completo[:80],
                len(completo),
                curto,
                APAC_MAX_NOME,
            )
        return curto

    def _nome_para_digitar_apac(self, lanc: Lancamento) -> Optional[str]:
        """Preferir nome da planilha; senao BIODATA sanitizado (nunca prontuario)."""
        from apac_bot.sheet import sanitizar_nome_opcao

        planilha = (lanc.paciente_nome or "").strip()
        if planilha and not planilha.isdigit():
            return self._aplicar_limite_nome_apac(planilha, rotulo="NOME")
        bruto = self._valor_biodata_ou_refrescar(lanc, "nome", rotulo="NOME")
        if not bruto:
            return None
        limpo = sanitizar_nome_opcao(bruto, lanc.prontuario)
        if not limpo:
            return None
        return self._aplicar_limite_nome_apac(limpo, rotulo="NOME")

    def _nome_mae_para_digitar_apac(self, lanc: Lancamento) -> Optional[str]:
        """Mae do BIODATA; rejeita vazio ou igual ao nome do paciente."""
        from apac_bot.sheet import nome_mae_valido

        pac_nome = (lanc.paciente_nome or "").strip()
        mae = self._valor_biodata_ou_refrescar(
            lanc, "nome_mae", rotulo="NOME DA MAE"
        )
        if nome_mae_valido(mae, pac_nome):
            return self._aplicar_limite_nome_apac(
                (mae or "").strip(), rotulo="NOME DA MAE"
            )
        # Refresh ja pode ter ocorrido em _valor_biodata; tenta de novo se connector
        if self._biodata_connector is not None and not nome_mae_valido(mae, pac_nome):
            refrescar_paciente_biodata(self._biodata_connector, lanc)
            mae = (
                (lanc.paciente.nome_mae or "").strip() if lanc.paciente else None
            )
        if nome_mae_valido(mae, pac_nome):
            return self._aplicar_limite_nome_apac(
                (mae or "").strip(), rotulo="NOME DA MAE"
            )
        return None

    def aceitar_nome_se_preenchido(self, lanc: Lancamento) -> None:
        """Apos SITUACAO DE RUA: aceita NOME se veio do CPF; senao digita planilha."""
        digita = self._nome_para_digitar_apac(lanc)
        if digita:
            log.info("NOME a digitar (se APAC vazio): %r", digita[:80])
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="NOME",
            flag_attr="_nome_aceito",
            max_chars=APAC_MAX_NOME,
            vazio_digita=digita if digita else "",
            marcar_cpf_preencheu_se_lido=True,
        )

    def aceitar_nome_mae_se_preenchido(self, lanc: Lancamento) -> None:
        """Apos NOME: aceita MAE do APAC; se vazio digita BIODATA (nunca o nome do paciente)."""
        digita = self._nome_mae_para_digitar_apac(lanc)
        if digita:
            log.info("NOME DA MAE a digitar (se APAC vazio): %r", digita[:80])
        elif not self.dry_run:
            # Se APAC tambem estiver vazio, _aceitar com vazio_digita="" bloqueia —
            # mensagem clara se nao houver mae valida na origem
            pass
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="NOME DA MAE",
            flag_attr="_nome_mae_aceito",
            max_chars=APAC_MAX_NOME,
            vazio_digita=digita if digita else "",
        )

    def aceitar_nome_responsavel_se_preenchido(self, lanc: Lancamento) -> None:
        """Apos NOME DA MAE: Tab se preenchido; se vazio, digita O MESMO."""
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="NOME DO RESPONSAVEL",
            flag_attr="_nome_responsavel_aceito",
            max_chars=120,
            vazio_digita="O MESMO",
        )

    def _normalizar_leitura_campo(self, rotulo: str, texto: str) -> str:
        """
        Limpa leitura do buffer/clipboard quando a linha traz o proximo rotulo.
        Mantem o valor do APAC (nao valida conteudo) — so isola o campo.
        """
        t = (texto or "").strip()
        if not t:
            return ""
        ru = rotulo.upper()
        if ru == "CEP":
            # So CEP completo (8 digitos). "LOGRADOURO : 0" / "0" = vazio.
            m = re.match(r"^(\d{5}-?\d{3})\b", t)
            if m:
                dig = "".join(ch for ch in m.group(1) if ch.isdigit())
                return m.group(1) if len(dig) == 8 else ""
            # Digitos no inicio da linha (antes de LOGRADOURO)
            m2 = re.match(r"^(\d{8})\b", t)
            if m2:
                return m2.group(1)
            if "LOGRADOURO" in t.upper():
                # Valor do CEP esta a esquerda; se nao ha 8 digitos la, vazio
                esq = t.upper().split("LOGRADOURO", 1)[0]
                dig_esq = "".join(ch for ch in esq if ch.isdigit())
                return dig_esq if len(dig_esq) == 8 else ""
            digitos = "".join(ch for ch in t if ch.isdigit())
            if len(digitos) == 8:
                return digitos
            return ""
        if ru == "LOGRADOURO":
            # Mascara vazia no Magnético costuma vir como "0"
            if t in {"0", "00", ".", "-"} or not t:
                return ""
            if re.fullmatch(r"0+", t):
                return ""
            return t
        if ru == "ENDERECO":
            # Linha ENDERECO|NUMERO: buffer vazio vira "NUMERO:" / "NUMERO"
            tu = t.upper().strip()
            if re.fullmatch(r"N[UÚ]MERO\s*:?", tu):
                return ""
            if t in {".", "-", "0", "00"} or not t:
                return ""
            # Corta rotulo NUMERO a direita
            partes = re.split(r"\s+N[UÚ]MERO\s*:?", t, maxsplit=1, flags=re.I)
            esq = (partes[0] if partes else t).strip()
            if not esq or re.fullmatch(r"N[UÚ]MERO\s*:?", esq, flags=re.I):
                return ""
            return esq
        if ru == "NUMERO":
            tu = t.upper().strip()
            if re.fullmatch(r"N[UÚ]MERO\s*:?", tu):
                return ""
            if t in {"0", "00", ".", "-", ""} or not t:
                return ""
            if re.fullmatch(r"0+", t):
                return ""
            # Remove rotulo colado no inicio
            m = re.match(r"^N[UÚ]MERO\s*:?\s*(.*)$", t, flags=re.I)
            if m:
                return (m.group(1) or "").strip()
            return t
        if ru == "DATA DE NASCIMENTO":
            # Ex.: "15/12/1975 SEXO: ETNIA :" -> "15/12/1975"
            m = re.match(r"^(\d{2}/\d{2}/\d{4})\b", t)
            if m:
                return m.group(1)
            m = re.match(r"^(\d{8})\b", t)
            if m:
                return m.group(1)
            # Corta no rotulo seguinte
            m2 = re.split(r"\s+(SEXO|ETNIA|RACA|RAÇA)\b", t, maxsplit=1, flags=re.I)
            esq = (m2[0] if m2 else t).strip()
            # Mascara vazia Magnético: "/ /" / "//" / so barras e espacos
            so_mascara = re.sub(r"[\s/.\-]", "", esq)
            if not so_mascara:
                return ""
            return esq
        if ru == "SEXO":
            # So M/F/1/2. "ETNIA :" / "E" do rotulo seguinte = vazio
            tu = t.upper().strip()
            if re.match(r"^ETNIA\b", tu) or re.fullmatch(r"E", tu):
                return ""
            m = re.match(r"^([MF12])\b", tu)
            if m:
                return m.group(1)
            m2 = re.split(r"\s+(ETNIA|RACA|RAÇA)\b", t, maxsplit=1, flags=re.I)
            esq = (m2[0] if m2 else t).strip().upper()
            if re.fullmatch(r"[MF12]", esq):
                return esq
            if esq.startswith("MASC"):
                return "M"
            if esq.startswith("FEM"):
                return "F"
            return ""
        if ru == "RACA":
            m = re.search(r"\bRACA\s*:?\s*(0?[1-5])\b", t, re.I)
            if m:
                return m.group(1)
            m = re.fullmatch(r"0?[1-5]", t.strip())
            if m:
                return t.strip()
            m2 = re.match(r"^(0?[1-5])\b", t)
            if m2:
                return m2.group(1)
            # "03 ??" / lixo de mascara
            m3 = re.match(r"^(0?[1-5])\s*\?+", t.strip())
            if m3:
                return m3.group(1)
            return t
        return t

    def _cep_para_digitar_apac(self, lanc: Lancamento) -> str:
        """
        CEP do BIODATA (8 digitos) ou CEP_PADRAO_APAC se ausente/invalido.
        """
        origem = self._valor_biodata_ou_refrescar(lanc, "cep", rotulo="CEP")
        digitos = "".join(ch for ch in (origem or "") if ch.isdigit())
        if len(digitos) >= 8:
            return digitos[:8]
        log.warning(
            "CEP ausente/invalido na origem para %s — usando padrao %s",
            lanc.paciente_nome,
            CEP_PADRAO_APAC,
        )
        return CEP_PADRAO_APAC

    def aceitar_cep_se_preenchido(self, lanc: Lancamento) -> None:
        """
        CEP: Tab se preenchido (8 digitos); se vazio, digita BIODATA;
        se BIODATA sem CEP, digita CEP_PADRAO_APAC (nunca Tab-pular vazio).
        """
        digita = self._cep_para_digitar_apac(lanc)
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="CEP",
            flag_attr="_cep_aceito",
            max_chars=80,
            aceitar_enter_se_origem="cep",
            vazio_digita=digita,
            vazio_aceita_tab=False,
        )
        # Linha CEP+LOGRADOURO: se Tab nao tirou o foco do CEP, Tab extra 1x
        if self.dry_run:
            return
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
            if campo_compativel(campo, CampoApac.CEP, linha=linha):
                log.info("CEP: ainda no CEP apos aceite — Tab extra")
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_tab_apos_aceitar")
        except ConsoleScreenError as exc:
            log.warning("CEP: falha ao checar foco pos-aceite: %s", exc)

    def _selecionar_logradouro_f1(self, tipo: str) -> None:
        """
        LOGRADOURO so aceita codigo: F1 abre lista; digita tipo (TRAVESSA/RUA…);
        Enter seleciona; Tab avanca ao proximo campo.
        """
        digitar = _nome_profissional_f1(tipo)
        if not digitar:
            raise ApacBlockedError("LOGRADOURO F1: tipo vazio.")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("LOGRADOURO: F1 (lista) → filtrar %r", digitar)
        self._enviar_f1(hwnd)
        self._pausa("pos_f1")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._digitar_texto(digitar, hwnd)
        self._pausa("pos_digitar_curto")

        log.info("LOGRADOURO: Enter (selecionar tipo %s)", digitar)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("LOGRADOURO: Tab (avancar ao proximo campo)")
        self._enviar_tab(hwnd)
        self._pausa("pos_tab_apos_aceitar")

    def _cursor_ja_passou_logradouro(self) -> Optional[CampoApac]:
        """
        Fluxo ja cadastrado no APAC: apos CEP o Magnético pode pular LOGRADOURO
        e cair em ENDERECO/NUMERO/…. Retorna o campo atual se ja passou.
        """
        try:
            campo, _linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError:
            return None
        posteriores = {
            CampoApac.ENDERECO,
            CampoApac.NUMERO,
            CampoApac.COMPLEMENTO,
            CampoApac.BAIRRO,
            CampoApac.TELEFONE,
            CampoApac.EMAIL,
            CampoApac.NASCIMENTO,
            CampoApac.SEXO,
            CampoApac.ETNIA_RACA,
            CampoApac.MUNICIPIO,
        }
        if campo in posteriores:
            return campo
        return None

    def aceitar_logradouro_se_preenchido(self, lanc: Lancamento) -> None:
        """
        Dois fluxos apos CEP:
        - Ja cadastrado no APAC: Magnético pode ja estar em ENDERECO → so segue.
        - Cadastro novo: Tab se LOGRADOURO tem codigo; vazio → F1 pelo tipo
          do endereco BIODATA; sem tipo → Tab.
        """
        if self._logradouro_aceito:
            return

        if self.dry_run:
            end = (lanc.paciente.endereco if lanc.paciente else None) or ""
            tipo = tipo_logradouro_do_endereco(end)
            log.info(
                "[dry-run] LOGRADOURO — Tab se preenchido; "
                "vazio F1 tipo=%r a partir do endereco",
                tipo,
            )
            self._logradouro_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"Verificar LOGRADOURO de {lanc.paciente_nome} (F1 se vazio)? digite s: "
            )
            if not ok:
                raise ApacBlockedError(
                    "operador recusou verificar LOGRADOURO no APAC"
                )

        self._pausa("pre_campo")
        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)

        # Fluxo cadastrado: CEP ja avancou alem do LOGRADOURO
        passou = self._cursor_ja_passou_logradouro()
        if passou is not None:
            log.info(
                "LOGRADOURO: Magnético ja em %s (paciente ja no APAC) — seguindo.",
                passou.value,
            )
            self._logradouro_aceito = True
            return

        linha_gate = self.exigir_campo(CampoApac.LOGRADOURO, passo="LOGRADOURO")
        bruto = (
            extrair_valor_campo_linha(linha_gate, campo=CampoApac.LOGRADOURO)
            or ""
        ).strip()
        texto = self._normalizar_leitura_campo("LOGRADOURO", bruto)
        digitos = "".join(ch for ch in texto if ch.isdigit())
        preenchido = bool(digitos)

        if preenchido:
            log.info(
                "LOGRADOURO preenchido no APAC: %s — Tab.",
                digitos[:20],
            )
            hwnd = self._ativar_janela_apac(clicar_centro=False)
            self._enviar_tab(hwnd)
            self._pausa("pos_tab_apos_aceitar")
            self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Tab em LOGRADOURO")
            self._logradouro_aceito = True
            log.info("LOGRADOURO: Tab (aceitar) — proximo campo.")
            return

        endereco = (lanc.paciente.endereco if lanc.paciente else None) or ""
        if not endereco.strip():
            # Sem rebusca por prontuario; so relê cadastro aberto se connector ligado
            endereco = (
                self._valor_biodata_ou_refrescar(
                    lanc, "endereco", rotulo="ENDERECO"
                )
                or ""
            )
        tipo = tipo_logradouro_do_endereco(endereco)
        if not tipo:
            # Tab em LOGRADOURO vazio trava o foco — F1 RUA como fallback
            log.warning(
                "LOGRADOURO vazio e sem tipo no endereco %r — F1 fallback RUA.",
                endereco[:60],
            )
            tipo = "RUA"
        else:
            log.info(
                "LOGRADOURO vazio — F1 com tipo %r (endereco=%r)",
                tipo,
                endereco[:60],
            )
        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"LOGRADOURO F1 '{tipo}' — digite s: "
            )
            if not ok:
                raise ApacBlockedError(
                    "operador recusou F1 no LOGRADOURO"
                )
        aguardar_enter_solto()
        self._selecionar_logradouro_f1(tipo)
        self.exigir_tela(
            TelaApac.IDENTIFICACAO, passo="apos F1 LOGRADOURO"
        )
        # Recovery: lista F1 ainda aberta → Enter; se ainda no LOGRADOURO → Tab
        try:
            buf = (self.ler_tela_console() or "").upper()
            if "ENTER=SELECIONA" in buf.replace(" ", ""):
                log.warning(
                    "LOGRADOURO: lista F1 ainda aberta — Enter recovery"
                )
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_enter(hwnd)
                self._pausa("pos_enter_form")
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_tab_apos_aceitar")
        except ConsoleScreenError as exc:
            log.warning("LOGRADOURO: checagem pos-F1 falhou: %s", exc)
        self._logradouro_aceito = True
        log.info("LOGRADOURO: F1 ok (%s) — proximo campo.", tipo)

    def aceitar_endereco_se_preenchido(self, lanc: Lancamento) -> None:
        """Apos LOGRADOURO: Tab se preenchido; vazio digita BIODATA ou Tab."""
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="ENDERECO",
            flag_attr="_endereco_aceito",
            max_chars=120,
            aceitar_enter_se_origem="endereco",
            vazio_aceita_tab=True,
        )
        # Linha ENDERECO+NUMERO: se Tab nao tirou o foco do ENDERECO, Tab extra 1x
        if self.dry_run:
            return
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
            if campo_compativel(campo, CampoApac.ENDERECO, linha=linha):
                log.info("ENDERECO: ainda no ENDERECO apos aceite — Tab extra")
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_tab_apos_aceitar")
        except ConsoleScreenError as exc:
            log.warning("ENDERECO: falha ao checar foco pos-aceite: %s", exc)

    def aceitar_numero_endereco_se_preenchido(self, lanc: Lancamento) -> None:
        """
        Apos ENDERECO: Tab se preenchido; vazio digita BIODATA ou Tab.
        Nao usa 'confia no CPF' — isso mandava Tab cego e ia para PROCEDIMENTOS.
        """
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="NUMERO",
            flag_attr="_numero_end_aceito",
            max_chars=20,
            aceitar_enter_se_origem="numero",
            vazio_aceita_tab=True,
        )

    def aceitar_complemento_se_preenchido(self, lanc: Lancamento) -> None:
        """
        COMPLEMENTO nao obrigatorio: sem clipboard — so 1 Tab para o BAIRRO.
        """
        if self._complemento_aceito:
            return

        if self.dry_run:
            log.info(
                "[dry-run] COMPLEMENTO: 1 Tab, sem ler clipboard — %s",
                lanc.paciente_nome,
            )
            self._complemento_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"COMPLEMENTO de {lanc.paciente_nome} — digite s para Tab (pular): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Tab no COMPLEMENTO")

        aguardar_enter_solto()
        self.exigir_campo(CampoApac.COMPLEMENTO, passo="COMPLEMENTO")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("COMPLEMENTO: Tab")
        self._enviar_tab(hwnd)
        self._pausa("pos_tab")
        self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Tab em COMPLEMENTO")

        self._complemento_aceito = True
        log.info("COMPLEMENTO: Tab ok — proximo campo (BAIRRO).")

    def aceitar_bairro_se_preenchido(self, lanc: Lancamento) -> None:
        """Apos COMPLEMENTO: Tab se preenchido; vazio digita BIODATA ou Tab."""
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="BAIRRO",
            flag_attr="_bairro_aceito",
            max_chars=80,
            aceitar_enter_se_origem="bairro",
            vazio_aceita_tab=True,
        )

    def aceitar_telefone_se_preenchido(self, lanc: Lancamento) -> None:
        """
        TELEFONE nao obrigatorio: sem clipboard — so 2 Tabs (DDD + numero).
        """
        if self._telefone_ddd_aceito and self._telefone_num_aceito:
            return

        if self.dry_run:
            log.info(
                "[dry-run] TELEFONE: 2 Tabs (DDD + numero), sem ler clipboard — %s",
                lanc.paciente_nome,
            )
            self._telefone_ddd_aceito = True
            self._telefone_num_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"TELEFONE de {lanc.paciente_nome} — digite s para 2 Tabs (DDD + numero): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Tabs no TELEFONE")

        aguardar_enter_solto()
        self.exigir_campo(CampoApac.TELEFONE, passo="TELEFONE")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("TELEFONE: Tab 1/2 (DDD)")
        self._enviar_tab(hwnd)
        self._pausa("pos_tab")
        self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Tab TELEFONE DDD")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("TELEFONE: Tab 2/2 (numero)")
        self._enviar_tab(hwnd)
        self._pausa("pos_tab")
        self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Tab TELEFONE numero")

        self._telefone_ddd_aceito = True
        self._telefone_num_aceito = True
        log.info("TELEFONE: 2 Tabs ok — proximo campo (EMAIL).")

    def aceitar_email_se_preenchido(self, lanc: Lancamento) -> None:
        """EMAIL nao obrigatorio: sem clipboard — so 1 Tab."""
        if self._email_aceito:
            return

        if self.dry_run:
            log.info(
                "[dry-run] EMAIL: 1 Tab, sem ler clipboard — %s",
                lanc.paciente_nome,
            )
            self._email_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"EMAIL de {lanc.paciente_nome} — digite s para Tab (pular): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Tab no EMAIL")

        aguardar_enter_solto()
        self.exigir_campo(CampoApac.EMAIL, passo="EMAIL")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("EMAIL: Tab")
        self._enviar_tab(hwnd)
        self._pausa("pos_tab")
        self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Tab em EMAIL")

        self._email_aceito = True
        log.info("EMAIL: Tab ok — proximo campo (DATA DE NASCIMENTO).")

    def aceitar_nascimento_se_preenchido(self, lanc: Lancamento) -> None:
        """DATA DE NASCIMENTO: Tab se preenchido; vazio digita BIODATA (avança sozinho)."""
        bruto = self._valor_biodata_ou_refrescar(
            lanc, "nascimento", rotulo="DATA DE NASCIMENTO"
        )
        digita = nascimento_ddmmaaaa(bruto) if bruto else None
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="DATA DE NASCIMENTO",
            flag_attr="_nascimento_aceito",
            max_chars=80,
            vazio_digita=digita if digita else "",
        )
        if self.dry_run:
            return
        try:
            # So cx==NASCIMENTO (linha tripla tambem tem SEXO/ETNIA)
            campo, _linha, _cx = identificar_campo_cursor(self._pids_apac())
            if campo == CampoApac.NASCIMENTO:
                log.info("DATA DE NASCIMENTO: ainda no campo apos aceite — Tab")
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_tab_apos_aceitar")
        except ConsoleScreenError as exc:
            log.warning(
                "DATA DE NASCIMENTO: falha ao checar foco pos-aceite: %s", exc
            )

    def aceitar_sexo_se_preenchido(self, lanc: Lancamento) -> None:
        """SEXO: Tab se preenchido; vazio digita M/F do BIODATA (avança sozinho para RACA)."""
        bruto = self._valor_biodata_ou_refrescar(lanc, "sexo", rotulo="SEXO")
        digita = sexo_para_apac(bruto)
        self._aceitar_campo_texto_se_preenchido(
            lanc,
            rotulo="SEXO",
            flag_attr="_sexo_aceito",
            max_chars=80,
            vazio_digita=digita if digita else "",
        )
        if self.dry_run:
            return
        try:
            campo, _linha, _cx = identificar_campo_cursor(self._pids_apac())
            if campo == CampoApac.SEXO:
                log.info("SEXO: ainda no campo apos aceite — Tab")
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_tab_apos_aceitar")
        except ConsoleScreenError as exc:
            log.warning("SEXO: falha ao checar foco pos-aceite: %s", exc)

    def aceitar_raca_se_preenchido(self, lanc: Lancamento) -> None:
        """
        RACA/ETNIA:
        - exige rotulo ETNIA/RACA na linha do cursor (sem Shift+Tab)
        - se ja tem codigo 01-05: ok (sem Tab)
        - se campo vazio: digita SO 03 (sem Tab; Enter fica em avancar_para_procedimentos)
        """
        if self._raca_aceito:
            return

        if self.dry_run:
            log.info("[dry-run] RACA/ETNIA — aceitar ou digitar 03 (sem Tab)")
            self._raca_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"RACA/ETNIA de {lanc.paciente_nome} — digite s para conferir: "
            )
            if not ok:
                raise ApacBlockedError("operador recusou RACA/ETNIA")

        self._pausa("pos_raca_pre")
        aguardar_enter_solto()
        # Gate por rotulo — TELEFONE/MUNICIPIO etc. abortam aqui (nao digita 03)
        # Um unico read: linha do gate + extrai valor de RACA (sem 2o AttachConsole)
        linha_gate = self.exigir_campo(CampoApac.ETNIA_RACA, passo="RACA")
        bruto = (
            extrair_valor_campo_linha(linha_gate, campo=CampoApac.ETNIA_RACA) or ""
        ).strip()
        texto = self._normalizar_leitura_campo("RACA", bruto)
        # Fallback: codigo na linha completa do gate (ex.: "RACA: 03 ??")
        if not _texto_parece_codigo_raca(texto) and linha_gate:
            m = re.search(r"\bRACA\s*:?\s*(0?[1-5])\b", linha_gate, re.I)
            if m:
                texto = m.group(1)
        log.info(
            "RACA leitura — buffer=%r normalizado=%r linha=%r",
            bruto[:60],
            texto[:40],
            (linha_gate or "")[:70],
        )

        if _texto_parece_codigo_raca(texto):
            log.info("RACA ja preenchida (%s) — pronto para Enter.", texto)
            self._raca_aceito = True
            return

        # Municipio vazou na leitura — nao digitar 03
        if _texto_parece_municipio_ibge(bruto) or _texto_parece_municipio_ibge(texto):
            raise ApacBlockedError(
                "RACA: leitura ainda parece MUNICIPIO "
                f"({bruto[:40]!r}). Ajuste o foco em RACA e rode de novo."
            )

        # So digita 03 se o campo estiver vazio (ou lixo minimo)
        if texto and texto not in {":", "-", ".", "0", "??", "?"}:
            raise ApacBlockedError(
                f"RACA: valor inesperado {texto!r} — nao sobrescreve. "
                "Confira o campo RACA no APAC."
            )

        if self._confirmar_nav():
            ok = self.confirm_fn("RACA vazia — digite s para enviar 03 (sem Tab): ")
            if not ok:
                raise ApacBlockedError("operador recusou digitar RACA=03")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        enviar_tecla_hwnd(hwnd, VK_HOME, _SCAN_HOME, nome="Home")
        self._pausa("pos_home")
        self._digitar_texto("03", hwnd)
        self._pausa("pos_raca_digitar")
        self._raca_aceito = True
        log.info("RACA=03 digitado — proximo: Enter para PROCEDIMENTOS.")

    def avancar_para_procedimentos(self) -> None:
        """
        Apos RACA: Enter abre PROCEDIMENTOS REALIZADOS
        (foco automatico em Cod. Procedimento).

        Dois contextos (nao misturar):
        - APAC ja preenchido / RACA so aceita: permanece em IDENTIFICACAO → Enter.
        - Cadastro vazio (digita RACA=03): Magnético as vezes ja abre PROCEDIMENTOS
          → so entao pula o Enter e segue o fluxo mapeado (nao aborta).
        """
        if self._procedimentos_tela_ok:
            return

        if self.dry_run:
            log.info("[dry-run] Enter apos RACA → tela PROCEDIMENTOS")
            self._procedimentos_tela_ok = True
            return

        if not self._raca_aceito:
            raise ApacBlockedError(
                "avancar_para_procedimentos: RACA ainda nao foi aceita."
            )

        aguardar_enter_solto()
        tela, _texto = self.classificar_tela_atual()
        # So pula Enter se JA estiver em PROCEDIMENTOS (avancou sozinho).
        # Se ainda IDENTIFICACAO (contexto APAC preenchido), Enter obrigatorio.
        if tela == TelaApac.PROCEDIMENTOS:
            log.info(
                "Ja em PROCEDIMENTOS apos RACA — seguindo sem Enter "
                "(contexto digitar RACA / Magnético avancou sozinho)."
            )
            self._procedimentos_tela_ok = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "RACA ok — digite s para ENTER (ir a PROCEDIMENTOS): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Enter apos RACA")

        self.exigir_tela(
            TelaApac.IDENTIFICACAO, passo="antes Enter RACA→PROCEDIMENTOS"
        )
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Enter apos RACA — abrindo PROCEDIMENTOS REALIZADOS")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")
        self.exigir_tela(
            TelaApac.PROCEDIMENTOS, passo="apos Enter RACA→PROCEDIMENTOS"
        )
        self._procedimentos_tela_ok = True
        log.info(
            "Tela PROCEDIMENTOS confirmada — foco esperado em Cod. Procedimento."
        )

    @staticmethod
    def _codigo_procedimento_digitar(codigo: str) -> str:
        """
        Mascara do APAC (.. . . -) costuma aceitar so digitos.
        Se nao houver digitos, devolve o texto limpo.
        """
        t = (codigo or "").strip()
        digitos = "".join(ch for ch in t if ch.isdigit())
        return digitos if digitos else t

    def _dado_fixo(self, chave: str, default: str = "") -> str:
        return str(self.cfg.dados_fixos.get(chave) or default).strip()

    def _resolver_codigo_procedimento(self, lanc: Lancamento) -> str:
        """dados_fixos.codigo_procedimento (UI futura) ou COD da planilha."""
        fixo = self._dado_fixo("codigo_procedimento")
        if fixo:
            return fixo
        return (lanc.codigo_apac or lanc.codigo_original or "").strip()

    def _exigir_proc(self, campo: CampoApac, *, passo: str) -> str:
        """
        Gate de campo em PROCEDIMENTOS sem releitura full do buffer
        (ja confirmamos a tela em entrar_procedimentos_apos_raca).
        """
        if not self._procedimentos_tela_ok:
            raise ApacBlockedError(
                f"{passo}: ainda nao esta em PROCEDIMENTOS."
            )
        if self.dry_run:
            log.info("[dry-run] exigir_proc %s no passo %s", campo.value, passo)
            return ""
        try:
            atual, linha, cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"Passo '{passo}': falha ao ler campo no cursor: {exc}"
            ) from exc
        if not campo_compativel(atual, campo, linha=linha):
            raise ApacBlockedError(
                f"Passo '{passo}': esperava campo {campo.value}, "
                f"encontrou {atual.value} (linha: {linha[:80]!r}). "
                "Pare — ajuste o foco ou rode dump-apac-screen."
            )
        log.info(
            "Campo OK passo=%s esperado=%s lido=%s cx=%s linha=%r",
            passo,
            campo.value,
            atual.value,
            cx,
            linha[:60],
        )
        return linha

    def _exigir_proc_com_tab(
        self, campo: CampoApac, *, passo: str, max_tabs: int = 3
    ) -> str:
        """
        Exige o campo na tela PROCEDIMENTOS; se o foco estiver em outro
        (ex.: Quantidade vs CNS na mesma linha), envia Tab e tenta de novo.
        """
        ultimo: Optional[ApacBlockedError] = None
        for tentativa in range(max_tabs + 1):
            try:
                return self._exigir_proc(campo, passo=passo)
            except ApacBlockedError as exc:
                ultimo = exc
                if tentativa >= max_tabs:
                    break
                log.warning(
                    "%s: campo errado (%s) — Tab %s/%s e tenta de novo.",
                    passo,
                    exc,
                    tentativa + 1,
                    max_tabs,
                )
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                self._enviar_tab(hwnd)
                self._pausa("pos_proc_tab")
        assert ultimo is not None
        raise ultimo

    def preencher_cod_procedimento(self, lanc: Lancamento) -> None:
        """
        Digita Cod. Procedimento: dados_fixos.codigo_procedimento se setado
        (dinamico na UI futura), senao planilha. Magnético avança sozinho ao CBO.
        """
        if self._cod_procedimento_preenchido:
            return

        bruto = self._resolver_codigo_procedimento(lanc)
        digitar = self._codigo_procedimento_digitar(bruto)
        if not digitar:
            raise ApacBlockedError(
                f"COD procedimento vazio (dados_fixos/planilha) "
                f"para '{lanc.paciente_nome}'."
            )

        if self.dry_run:
            log.info(
                "[dry-run] COD.PROCEDIMENTO — %s → %s (origem %r)",
                lanc.paciente_nome,
                digitar,
                bruto,
            )
            self._cod_procedimento_preenchido = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"COD.PROCEDIMENTO {digitar} ({bruto}) — digite s para enviar: "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar COD.PROCEDIMENTO")

        aguardar_enter_solto()
        self._exigir_proc(CampoApac.COD_PROCEDIMENTO, passo="COD.PROCEDIMENTO")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info(
            "Digitando COD.PROCEDIMENTO %s (origem %r) — sem Tab",
            digitar,
            bruto,
        )
        self._digitar_texto(digitar, hwnd)
        self._pausa("pos_proc_digitar")
        self._cod_procedimento_preenchido = True
        log.info("COD.PROCEDIMENTO ok — proximo: C.B.O.")

    def preencher_cbo(self) -> None:
        """C.B.O. fixo (dados_fixos.cbo)."""
        if self._cbo_preenchido:
            return

        cbo = self._dado_fixo("cbo", "225265")
        digitar = "".join(ch for ch in cbo if ch.isdigit()) or cbo
        if not digitar:
            raise ApacBlockedError("dados_fixos.cbo vazio.")

        if self.dry_run:
            log.info("[dry-run] C.B.O. — %s", digitar)
            self._cbo_preenchido = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(f"C.B.O. {digitar} — digite s para enviar: ")
            if not ok:
                raise ApacBlockedError("operador recusou digitar C.B.O.")

        aguardar_enter_solto()
        self._exigir_proc_com_tab(CampoApac.CBO, passo="C.B.O.")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando C.B.O. %s (sem Tab)", digitar)
        self._digitar_texto(digitar, hwnd)
        self._pausa("pos_proc_digitar")
        self._cbo_preenchido = True
        log.info("C.B.O. ok — proximo: Quantidade.")

    def preencher_quantidade_procedimento(self) -> None:
        """Quantidade sempre 1 (dados_fixos.quantidade_procedimento)."""
        if self._qtd_procedimento_preenchida:
            return

        qtd = self._dado_fixo("quantidade_procedimento", "1") or "1"
        digitar = "".join(ch for ch in qtd if ch.isdigit()) or "1"

        if self.dry_run:
            log.info("[dry-run] Quantidade — %s", digitar)
            self._qtd_procedimento_preenchida = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(f"Quantidade {digitar} — digite s para enviar: ")
            if not ok:
                raise ApacBlockedError("operador recusou digitar Quantidade")

        aguardar_enter_solto()
        self._exigir_proc_com_tab(CampoApac.QUANTIDADE, passo="QUANTIDADE")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando Quantidade %s (sem Tab)", digitar)
        self._digitar_texto(digitar, hwnd)
        self._pausa("pos_proc_digitar")
        # Garante avanço para CNS (mesma linha — nao digitar CNS em Quantidade)
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._enviar_tab(hwnd)
        self._pausa("pos_proc_tab")
        self._qtd_procedimento_preenchida = True
        log.info("Quantidade ok — Tab para CNS Executante.")

    def preencher_cns_executante(self) -> None:
        """CNS Executante dinamico (dados_fixos.cns_executante; UI futura)."""
        if self._cns_executante_preenchido:
            return

        cns = self._dado_fixo("cns_executante")
        digitar = "".join(ch for ch in cns if ch.isdigit()) or cns
        if not digitar:
            raise ApacBlockedError("dados_fixos.cns_executante vazio.")

        if self.dry_run:
            log.info("[dry-run] CNS Executante — %s", digitar)
            self._cns_executante_preenchido = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"CNS Executante {digitar} — digite s para enviar: "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar CNS Executante")

        aguardar_enter_solto()
        # Tab se ainda estiver em Quantidade (linha compartilhada)
        self._exigir_proc_com_tab(CampoApac.CNS_EXECUTANTE, passo="CNS EXECUTANTE")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Digitando CNS Executante %s (sem Tab)", digitar)
        self._digitar_texto(digitar, hwnd)
        self._pausa("pos_proc_digitar")
        # Sem Tab cego — Magnético pode pular Equipe vazia; pular_equipe decide
        self._cns_executante_preenchido = True
        log.info("CNS Executante ok — proximo: Equipe / Servico.")

    def _campo_proc_atual(self) -> tuple[CampoApac, str]:
        """Campo + linha do cursor (sem full buffer / exigir_tela)."""
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"Falha ao ler campo em PROCEDIMENTOS: {exc}"
            ) from exc
        return campo, linha

    def _tab_proc(self, *, passo: str) -> None:
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("%s: Tab", passo)
        self._enviar_tab(hwnd)
        self._pausa("pos_proc_tab")

    def _enter_proc(self, *, passo: str) -> None:
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("%s: Enter", passo)
        self._enviar_enter(hwnd)
        self._pausa("pos_proc_tab")

    def pular_equipe(self) -> None:
        """
        Equipe vazia: 1 Tab se o foco estiver nela.
        Se o Magnético ja pulou (foco em Servico/Classif), so marca ok.
        """
        if self._equipe_pulada:
            return

        if self.dry_run:
            log.info("[dry-run] Equipe — Tab (vazio) ou ja pulada")
            self._equipe_pulada = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn("Equipe vazia — digite s para conferir/Tab: ")
            if not ok:
                raise ApacBlockedError("operador recusou passo Equipe")

        aguardar_enter_solto()
        acao = None
        for _ in range(3):
            campo, linha = self._campo_proc_atual()
            acao = decidir_acao_equipe(campo)
            log.info(
                "Equipe: foco=%s acao=%s linha=%r",
                campo.value,
                acao,
                linha[:60],
            )
            if acao == "ja_pulada":
                self._equipe_pulada = True
                log.info("Equipe ja pulada pelo Magnético — seguindo.")
                return
            if acao == "tab":
                self._tab_proc(passo="EQUIPE (vazio)")
                self._equipe_pulada = True
                log.info("Equipe ok — proximo: Servico (Tab aceitar).")
                return
            # ainda no CNS (ou anterior): Tab uma vez e rele
            self._tab_proc(passo="EQUIPE (sair do CNS)")
        raise ApacBlockedError(
            f"Equipe: nao foi possivel posicionar (ultima acao={acao})."
        )

    def aceitar_servico_se_preenchido(self) -> None:
        """Servico ja vem preenchido — Tab sem sobrescrever."""
        if self._servico_aceito:
            return

        if self.dry_run:
            log.info("[dry-run] Servico — Tab (aceitar sem redigitar)")
            self._servico_aceito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn("Servico — digite s para Tab (aceitar): ")
            if not ok:
                raise ApacBlockedError("operador recusou Tab em Servico")

        aguardar_enter_solto()
        for _ in range(3):
            campo, linha = self._campo_proc_atual()
            acao = decidir_acao_servico(campo)
            log.info(
                "Servico: foco=%s acao=%s linha=%r",
                campo.value,
                acao,
                linha[:60],
            )
            if acao == "ja_ok":
                self._servico_aceito = True
                log.info("Servico ja ultrapassado — seguindo para Classif.")
                return
            if acao == "tab":
                self._tab_proc(passo="SERVICO (aceitar)")
                self._servico_aceito = True
                log.info("Servico ok — proximo: Classificacao (Tab aceitar).")
                return
            self._tab_proc(passo="SERVICO (avancar)")
        raise ApacBlockedError("Servico: nao foi possivel posicionar.")

    def aceitar_classificacao_se_preenchido(self) -> None:
        """Classificacao ja vem preenchida — Enter sem sobrescrever (proximo = CID)."""
        if self._classificacao_aceita:
            return

        if self.dry_run:
            log.info("[dry-run] Classificacao — Enter (aceitar sem redigitar)")
            self._classificacao_aceita = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "Classificacao — digite s para Enter (aceitar): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Enter em Classificacao")

        aguardar_enter_solto()
        for _ in range(3):
            campo, linha = self._campo_proc_atual()
            acao = decidir_acao_classificacao(campo)
            log.info(
                "Classificacao: foco=%s acao=%s linha=%r",
                campo.value,
                acao,
                linha[:60],
            )
            if acao == "tab":
                # Magnético: Enter aceita Classif. e vai ao proximo (CID)
                self._enter_proc(passo="CLASSIFICACAO (aceitar)")
                self._classificacao_aceita = True
                log.info(
                    "Classificacao ok — Enter para proximo campo (CID)."
                )
                return
            self._tab_proc(passo="CLASSIFICACAO (avancar)")
        raise ApacBlockedError("Classificacao: nao foi possivel posicionar.")

    def preencher_motivo_saida(self) -> None:
        """
        Na lista PROCEDIMENTOS REALIZADOS: Tab ate MOTIVO SAIDA
        (Enter na grade edita o registro), digita 12 (padrao) ou 15 (glaucoma)
        e Enter. Nao preenche DATA ALTA.
        """
        if self._motivo_saida_preenchido:
            return

        digitar = "15" if self.cfg.modalidade == MODALIDADE_GLAUCOMA else "12"

        if self.dry_run:
            log.info("[dry-run] MOTIVO SAIDA — Tab, %s + Enter", digitar)
            self._motivo_saida_preenchido = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"MOTIVO SAIDA {digitar} — digite s para enviar: "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar MOTIVO SAIDA")

        aguardar_enter_solto()
        if not self._procedimentos_tela_ok:
            raise ApacBlockedError(
                "MOTIVO SAIDA: ainda nao esta em PROCEDIMENTOS."
            )

        for tentativa in range(3):
            campo, linha = self._campo_proc_atual()
            log.info(
                "MOTIVO SAIDA: foco=%s tentativa=%s linha=%r",
                campo.value,
                tentativa + 1,
                linha[:60],
            )
            if campo == CampoApac.MOTIVO_SAIDA or campo_compativel(
                campo, CampoApac.MOTIVO_SAIDA, linha=linha
            ):
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                log.info("Digitando MOTIVO SAIDA %s", digitar)
                self._digitar_texto(digitar, hwnd)
                self._pausa("pos_proc_digitar")
                self._enter_proc(passo="MOTIVO SAIDA (aceitar)")
                self._motivo_saida_preenchido = True
                log.info(
                    "MOTIVO SAIDA ok (%s) — pare antes de DATA ALTA / salvar.",
                    digitar,
                )
                return
            if campo in (
                CampoApac.COD_PROCEDIMENTO,
                CampoApac.CBO,
                CampoApac.QUANTIDADE,
                CampoApac.CLASSIFICACAO,
            ):
                log.warning(
                    "MOTIVO SAIDA: foco em %s (edicao?) — Tab, nao Enter.",
                    campo.value,
                )
            # Grade / outro campo: Tab (Enter na lista = Alteracao)
            self._tab_proc(passo="MOTIVO SAIDA (focar)")
        raise ApacBlockedError(
            "MOTIVO SAIDA: nao foi possivel posicionar o cursor."
        )

    def preencher_data_alta_mes_anterior(self) -> None:
        """
        DATA ALTA/OBITO/TRANSF./MUDANCA PROCED.: ultimo dia do mes anterior
        (DDMMAAAA). Sem Enter (mascara).
        """
        if self._data_alta_preenchida:
            return

        _, fim = datas_validade_mes_anterior(
            fim_offset_meses=fim_offset_meses(self.cfg.modalidade)
        )
        fim_legivel = f"{fim[:2]}/{fim[2:4]}/{fim[4:]}"

        if self.dry_run:
            log.info("[dry-run] DATA ALTA — %s", fim_legivel)
            self._data_alta_preenchida = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                f"DATA ALTA {fim_legivel} — digite s (sem Enter): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou digitar DATA ALTA")

        aguardar_enter_solto()
        if not self._procedimentos_tela_ok:
            raise ApacBlockedError(
                "DATA ALTA: ainda nao esta em PROCEDIMENTOS."
            )

        for tentativa in range(3):
            campo, linha = self._campo_proc_atual()
            log.info(
                "DATA ALTA: foco=%s tentativa=%s linha=%r",
                campo.value,
                tentativa + 1,
                linha[:60],
            )
            if campo == CampoApac.DATA_ALTA or campo_compativel(
                campo, CampoApac.DATA_ALTA, linha=linha
            ):
                hwnd = self._ativar_janela_apac(clicar_centro=False)
                log.info("Digitando DATA ALTA %s (sem Enter)", fim)
                self._digitar_texto(fim, hwnd)
                self._pausa("pos_proc_digitar")
                self._data_alta_preenchida = True
                log.info(
                    "DATA ALTA ok (%s) — seguindo para DADOS COMPLEMENTARES.",
                    fim_legivel,
                )
                return
            self._tab_proc(passo="DATA ALTA (focar)")
        raise ApacBlockedError(
            "DATA ALTA: nao foi possivel posicionar o cursor."
        )

    def preencher_cid_dados_complementares(self) -> None:
        """
        Tela DADOS COMPLEMENTARES (foco C.I.D. PRINCIPAL):
          F1 -> Enter (1a opcao) -> Enter (SECUNDARIO vazio) -> Enter (CAUSAS)
        Para em SOLICITACAO/AUTORIZACAO (CARATER ATEND.) sem preencher.
        """
        if self._cid_complementares_ok:
            return

        if self.dry_run:
            log.info(
                "[dry-run] CID DADOS COMPLEMENTARES — F1 + 3 Enter "
                "(para em SOLICITACAO/CARATER)"
            )
            self._cid_complementares_ok = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "CID PRINCIPAL (F1 + 3 Enter) — digite s para enviar: "
            )
            if not ok:
                raise ApacBlockedError(
                    "operador recusou preencher CID DADOS COMPLEMENTARES"
                )

        if not self._data_alta_preenchida:
            raise ApacBlockedError(
                "CID complementares: DATA ALTA ainda nao preenchida."
            )

        aguardar_enter_solto()
        hwnd = self._ativar_janela_apac(clicar_centro=False)

        # Apos DATA ALTA (sem Enter): pode ainda estar em PROCEDIMENTOS
        tela, texto = self.classificar_tela_atual()
        if tela == TelaApac.PROCEDIMENTOS or (
            "DADOS COMPLEMENTARES" not in (texto or "").upper()
            and tela != TelaApac.DADOS_COMPLEMENTARES
        ):
            log.info(
                "CID: ainda nao em DADOS COMPLEMENTARES (tela=%s) — Enter 1x",
                tela.value,
            )
            self._enviar_enter(hwnd)
            self._pausa("pos_enter_form")
            tela, texto = self.classificar_tela_atual()

        if tela != TelaApac.DADOS_COMPLEMENTARES and (
            "DADOS COMPLEMENTARES" not in (texto or "").upper()
        ):
            raise ApacBlockedError(
                "CID complementares: esperava DADOS COMPLEMENTARES, "
                f"encontrou {tela.value} (preview: {preview_tela(texto)!r})."
            )

        # Gate leve: foco em CID PRINCIPAL (ou linha compativel)
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"CID complementares: falha ao ler campo no cursor: {exc}"
            ) from exc
        if not campo_compativel(
            campo, CampoApac.CID_PRINCIPAL, linha=linha
        ):
            log.warning(
                "CID: foco=%s linha=%r — seguindo mesmo assim (F1 no campo atual)",
                campo.value,
                linha[:60],
            )
        else:
            log.info("CID PRINCIPAL: foco ok linha=%r", linha[:60])

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("CID PRINCIPAL: F1 (ajuda / 1a opcao)")
        self._enviar_f1(hwnd)
        self._pausa("pos_f1")

        log.info("CID PRINCIPAL: Enter (aceitar 1a opcao)")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        log.info("CID SECUNDARIO: Enter (vazio)")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        def _eh_solicitacao(tela: TelaApac, texto: str) -> bool:
            upper = (texto or "").upper()
            return (
                tela == TelaApac.SOLICITACAO
                or "SOLICITACAO" in upper
                or "AUTORIZACAO" in upper
                or "AUTORIZAÇÃO" in upper
                or "CARATER ATEND" in upper
            )

        # CAUSAS ASSOCIADAS: Enter + ate 2 retries se ainda em DADOS COMPLEMENTARES
        max_causas_enter = 3
        tela = TelaApac.DESCONHECIDA
        texto = ""
        for i in range(1, max_causas_enter + 1):
            hwnd = self._ativar_janela_apac(clicar_centro=False)
            log.info(
                "CAUSAS ASSOCIADAS: Enter %s/%s (vazio) → SOLICITACAO",
                i,
                max_causas_enter,
            )
            self._enviar_enter(hwnd)
            self._pausa("pos_enter_form")
            tela, texto = self.classificar_tela_atual()
            if _eh_solicitacao(tela, texto):
                break
            if i < max_causas_enter:
                log.warning(
                    "CAUSAS: ainda tela=%s apos Enter %s — retry Enter",
                    tela.value,
                    i,
                )
        else:
            raise ApacBlockedError(
                "CID complementares: apos Enter em CAUSAS esperava "
                f"SOLICITACAO/AUTORIZACAO, encontrou {tela.value} "
                f"(preview: {preview_tela(texto)!r})."
            )

        self._cid_complementares_ok = True
        log.info(
            "CID DADOS COMPLEMENTARES ok — tela SOLICITACAO/AUTORIZACAO "
            "(foco CARATER ATEND.)."
        )

    def _selecionar_profissional_por_cns(self, cns: str, *, passo: str) -> None:
        """
        No campo CNS: F1 abre CONSULTA DE PROFISSIONAL; digita o CNS (CODIGO);
        Enter seleciona e fecha o menu. Nome e fragil no Magnético (Ø/0/O).
        """
        digitar = _cns_so_digitos(cns)
        if len(digitar) < 15:
            raise ApacBlockedError(
                f"{passo}: CNS do profissional invalido/ausente "
                f"(digitos={len(digitar)}; dados_fixos por clinica)."
            )

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("%s: F1 (consulta profissional) → CNS %s", passo, digitar)
        self._enviar_f1(hwnd)
        self._pausa("pos_f1")

        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._digitar_texto(digitar, hwnd)
        # Filtro precisa assentar antes do Enter (evita pegar 1a linha errada)
        self._pausa("pos_digitar")

        log.info("%s: Enter (selecionar profissional por CNS)", passo)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        texto = self.ler_tela_console()
        if "CONSULTA DE PROFISSIONAL" in (texto or "").upper():
            log.warning(
                "%s: menu ainda aberto apos Enter — novo Enter",
                passo,
            )
            self._enviar_enter(hwnd)
            self._pausa("pos_enter_form")

    def _ler_nome_profissional_tela(self) -> str:
        """Le o valor do campo NOME na tela SOLICITACAO (apos CNS/CPF)."""
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"NOME profissional: falha ao ler cursor: {exc}"
            ) from exc
        if campo_compativel(campo, CampoApac.NOME, linha=linha):
            bruto = (
                extrair_valor_campo_linha(linha, campo=CampoApac.NOME) or ""
            ).strip()
            if bruto:
                return bruto
        # Fallback: procura linha NOME: no buffer (evita NOME DA MAE / RESP)
        texto = self.ler_tela_console() or ""
        for raw in texto.splitlines():
            upper = raw.upper()
            if "NOME DA" in upper or "NOME DO" in upper:
                continue
            if re.search(r"\bNOME\b", upper):
                val = (
                    extrair_valor_campo_linha(raw, campo=CampoApac.NOME) or ""
                ).strip()
                if val:
                    return val
        return ""

    def _confirmar_profissional_apos_f1(
        self,
        cns: str,
        nome: Optional[str] = None,
        *,
        passo: str,
    ) -> None:
        """
        Apos F1 + Enter (pula CPF): confere CNS na tela; se nome configurado,
        confere NOME tambem. Aborta se nao bater (nao confirma profissional errado).
        """
        self._pausa("pre_campo")
        digitos = _cns_so_digitos(cns)
        texto = self.ler_tela_console() or ""
        # Magnético mascara CNS (ex.: 70560946967021-3) — comparar so digitos
        tela_digitos = _cns_so_digitos(texto)
        if digitos and digitos not in tela_digitos:
            raise ApacBlockedError(
                f"{passo}: esperava CNS {digitos} na tela apos F1, "
                f"nao encontrado. Pare e selecione o profissional correto."
            )
        log.info("%s: CNS confirmado na tela (%s)", passo, digitos)

        if nome and str(nome).strip():
            lido = self._ler_nome_profissional_tela()
            if lido and not _nome_profissional_compativel(nome, lido):
                raise ApacBlockedError(
                    f"{passo}: CNS {digitos} ok, mas NOME esperava {nome!r}, "
                    f"veio {lido!r}. Pare e revise no APAC."
                )
            if lido:
                log.info(
                    "%s: NOME confirmado %r (label %r)",
                    passo,
                    lido[:60],
                    nome[:60],
                )

    def preencher_solicitacao_autorizacao(self) -> None:
        """
        Tela SOLICITACAO/AUTORIZACAO:
          CARATER 01 → CNS medico (F1 por CNS) → NOME Enter → DT.SOLICITACAO
          → CNS autorizador (F1 por CNS) → NOME Enter → DT.AUTORIZACAO
          → COD.ORGAO + Enter → LISTA.

        CNS vem de dados_fixos (dinamico por clinica / UI futura).
        """
        if self._solicitacao_ok:
            return

        carater = self._dado_fixo("carater_atend", "01") or "01"
        medico_cns = (
            self._dado_fixo(
                "medico_solicitante_cns", MEDICO_SOLICITANTE_CNS_PADRAO
            )
            or MEDICO_SOLICITANTE_CNS_PADRAO
        )
        medico_nome = self._dado_fixo(
            "medico_solicitante_nome", MEDICO_SOLICITANTE_NOME_PADRAO
        ) or MEDICO_SOLICITANTE_NOME_PADRAO
        autorizador_cns = (
            self._dado_fixo("autorizador_cns", AUTORIZADOR_CNS_PADRAO)
            or AUTORIZADOR_CNS_PADRAO
        )
        autorizador_nome = self._dado_fixo(
            "autorizador_nome", AUTORIZADOR_NOME_PADRAO
        ) or AUTORIZADOR_NOME_PADRAO
        orgao = self._dado_fixo("cod_orgao_emiss", "M211130001")
        inicio, _fim = datas_validade_mes_anterior(
            fim_offset_meses=fim_offset_meses(self.cfg.modalidade)
        )
        inicio_legivel = f"{inicio[:2]}/{inicio[2:4]}/{inicio[4:]}"

        if self.dry_run:
            log.info(
                "[dry-run] SOLICITACAO — carater=%s medico_cns=%s (%r) "
                "autorizador_cns=%s (%r) dt=%s orgao=%s → LISTA",
                carater,
                _cns_so_digitos(medico_cns),
                medico_nome,
                _cns_so_digitos(autorizador_cns),
                autorizador_nome,
                inicio_legivel,
                orgao,
            )
            self._solicitacao_ok = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "SOLICITACAO/AUTORIZACAO (CARATER→LISTA) — digite s: "
            )
            if not ok:
                raise ApacBlockedError(
                    "operador recusou preencher SOLICITACAO/AUTORIZACAO"
                )

        if not _cns_so_digitos(medico_cns):
            raise ApacBlockedError(
                "dados_fixos.medico_solicitante_cns e obrigatorio "
                "(dinamico por clinica; UI futura)."
            )
        if not _cns_so_digitos(autorizador_cns):
            raise ApacBlockedError(
                "dados_fixos.autorizador_cns e obrigatorio "
                "(dinamico por clinica; UI futura)."
            )
        if not orgao:
            raise ApacBlockedError(
                "dados_fixos.cod_orgao_emiss e obrigatorio "
                "(dinamico por clinica; UI futura)."
            )

        aguardar_enter_solto()
        self.exigir_tela(TelaApac.SOLICITACAO, passo="SOLICITACAO/AUTORIZACAO")

        # 1) CARATER ATEND.
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        try:
            campo, linha, _cx = identificar_campo_cursor(self._pids_apac())
        except ConsoleScreenError as exc:
            raise ApacBlockedError(
                f"CARATER: falha ao ler campo: {exc}"
            ) from exc
        if not campo_compativel(campo, CampoApac.CARATER_ATEND, linha=linha):
            log.warning(
                "CARATER: foco=%s linha=%r — digitando mesmo assim",
                campo.value,
                linha[:60],
            )
        log.info("CARATER ATEND. %s + Enter", carater)
        self._digitar_texto(carater, hwnd)
        self._pausa("pos_digitar_curto")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        # 2) CNS medico responsavel (busca F1 pelo CNS, nao pelo nome)
        self._selecionar_profissional_por_cns(medico_cns, passo="CNS medico")
        log.info("CNS medico: Enter (pula CPF → NOME)")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        self._confirmar_profissional_apos_f1(
            medico_cns, medico_nome, passo="CNS medico"
        )
        log.info("NOME medico: Enter (aceitar preenchido)")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        # 3) DT.SOLICITACAO = 1o dia mes anterior
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("DT.SOLICITACAO %s (sem Enter extra)", inicio_legivel)
        self._digitar_texto(inicio, hwnd)
        self._pausa("pos_digitar_curto")

        # 4) CNS autorizador (busca F1 pelo CNS)
        self._selecionar_profissional_por_cns(
            autorizador_cns, passo="CNS autorizador"
        )
        log.info("CNS autorizador: Enter (pula CPF → NOME)")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        self._confirmar_profissional_apos_f1(
            autorizador_cns, autorizador_nome, passo="CNS autorizador"
        )
        log.info("NOME autorizador: Enter (aceitar preenchido)")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        # 5) DT.AUTORIZACAO
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("DT.AUTORIZACAO %s (sem Enter extra)", inicio_legivel)
        self._digitar_texto(inicio, hwnd)
        self._pausa("pos_digitar_curto")

        # 6) COD.ORGAO EMISS + Enter → LISTA
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("COD.ORGAO EMISS %s + Enter → LISTA", orgao)
        self._digitar_texto(orgao, hwnd)
        self._pausa("pos_digitar_curto")
        self._enviar_enter(hwnd)
        self._pausa("pos_enter_form")

        self.exigir_tela(TelaApac.LISTA, passo="apos SOLICITACAO (volta LISTA)")
        self._solicitacao_ok = True
        log.info(
            "SOLICITACAO/AUTORIZACAO ok — voltou a LISTA "
            "(pronto para Insert do proximo paciente)."
        )

    def iniciar_inclusao_insert(self) -> None:
        """
        Na lista ATUALIZACAO DE APAC: Insert inicia inclusao de novo cadastro.
        Sem clique no centro (pode interferir na lista).
        Uma vez por paciente (flag zerada via _reiniciar_flags_paciente).
        """
        if self._insert_inclusao_feito:
            return

        if self.dry_run:
            log.info("[dry-run] Insert (inclusao) na lista ATUALIZACAO DE APAC")
            self._insert_inclusao_feito = True
            return

        if self._confirmar_nav():
            ok = self.confirm_fn(
                "lista ATUALIZACAO DE APAC — digite s para INSERT (inclusao): "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Insert (inclusao)")

        self.exigir_tela(TelaApac.LISTA, passo="antes do Insert")
        hwnd = self._ativar_janela_apac(clicar_centro=False)
        log.info("Insert — inclusao de novo cadastro")
        self._enviar_insert(hwnd)
        self._pausa("pos_insert")

        self._insert_inclusao_feito = True
        self.exigir_tela(TelaApac.IDENTIFICACAO, passo="apos Insert")
        log.info("Insert ok — tela IDENTIFICACAO confirmada via buffer.")

    def navegar_ate_cadastro(self) -> None:
        """
        Apos abrir o APAC (MENU - PRINCIPAL, foco em A.P.A.C.):
          Enter 1 -> abre submenu (CADASTRO DE APAC / CONSISTENCIA)
          Enter 2 -> confirma CADASTRO DE APAC -> lista
          Se ainda MENU (Enter 2 nao 'pegou'), Enter extra ate LISTA (max 2).
        Uma vez por sessao.
        """
        if self._nav_inicial_feita:
            return

        usar = self.cfg.apac.get("usar_navegacao_inicial", True)
        if isinstance(usar, str):
            usar = usar.strip().lower() in {"1", "true", "sim", "yes"}
        if not usar:
            log.info("usar_navegacao_inicial=false — pulando navegação de menu.")
            self._nav_inicial_feita = True
            return

        if self.dry_run:
            log.info(
                "[dry-run] navegação: Enter submenu → Enter CADASTRO → lista "
                "(retry se ainda MENU)"
            )
            self._nav_inicial_feita = True
            return

        confirmar = self._confirmar_nav()
        intervalo = self._intervalo_nav_enter()
        log.info(
            "Navegação inicial: submenu A.P.A.C. → CADASTRO → lista%s "
            "(intervalo=%.2fs, velocidade=%s).",
            " (com s)" if confirmar else " (automatico)",
            intervalo,
            self._velocidade,
        )

        if confirmar:
            ok = self.confirm_fn(
                "1/2 MENU PRINCIPAL foco em A.P.A.C. — digite s para ENTER: "
            )
            if not ok:
                raise ApacBlockedError("operador recusou Enter 1/2 (A.P.A.C.)")

        self.exigir_tela(TelaApac.MENU, passo="navegacao inicial Enter 1/2")
        hwnd = self._ativar_janela_apac(clicar_centro=True)
        log.info("Enter 1 — abre submenu A.P.A.C. (CADASTRO / CONSISTENCIA)")
        self._enviar_enter(hwnd)
        time.sleep(intervalo)

        # Enter 2 (+ retry): confirmar CADASTRO ate sair do MENU
        max_confirm = 2
        for tentativa in range(1, max_confirm + 1):
            if confirmar:
                ok = self.confirm_fn(
                    f"CADASTRO DE APAC selecionado? digite s para ENTER "
                    f"({tentativa}/{max_confirm}): "
                )
                if not ok:
                    raise ApacBlockedError(
                        f"operador recusou Enter CADASTRO ({tentativa}/{max_confirm})"
                    )
            # Sem clique: clique no centro fecha o submenu
            hwnd = self._ativar_janela_apac(clicar_centro=False)
            log.info(
                "Enter %s/%s — confirmar CADASTRO DE APAC",
                tentativa,
                max_confirm,
            )
            self._enviar_enter(hwnd)
            self._pausa("pos_nav_retry")
            tela, texto = self.classificar_tela_atual()
            if tela == TelaApac.LISTA:
                break
            if tela == TelaApac.PROCEDIMENTOS:
                raise ApacBlockedError(
                    "Navegacao: caiu em PROCEDIMENTOS ao confirmar CADASTRO "
                    f"(preview: {preview_tela(texto)!r})."
                )
            if tela != TelaApac.MENU:
                # Saiu do menu mas classificador ainda nao ve LISTA — exige LISTA abaixo
                log.warning(
                    "Apos Enter CADASTRO tela=%s (preview: %s) — seguindo para gate LISTA",
                    tela.value,
                    preview_tela(texto),
                )
                break
            log.warning(
                "Ainda MENU apos Enter CADASTRO %s/%s — novo Enter "
                "(submenu pode nao ter confirmado).",
                tentativa,
                max_confirm,
            )
        else:
            # esgotou retries ainda em MENU
            pass

        self._nav_inicial_feita = True
        self.exigir_tela(TelaApac.LISTA, passo="apos navegacao (lista)")
        log.info(
            "Navegação concluída — lista ATUALIZACAO DE APAC. "
            "Proximo passo sera Insert (nao Enter)."
        )

    def _rodar_sequencia_passos(
        self,
        passos: list[dict[str, Any]],
        lanc: Lancamento,
        *,
        permitir_salvar: bool,
    ) -> ApacStepResult:
        parado_antes_salvar = False
        for passo in passos:
            acao = (passo.get("acao") or "").lower()
            step_id = passo.get("id") or acao
            is_save = acao in {"salvar", "save"} or bool(passo.get("e_salvamento"))

            if is_save and not permitir_salvar:
                log.info(
                    "Parando antes do salvamento (apac.permitir_salvar=false). "
                    "Revisão humana necessária. passo=%s identidade=%s",
                    step_id,
                    lanc.identidade[:8],
                )
                parado_antes_salvar = True
                break

            if passo.get("confirmar_operador"):
                tela = passo.get("tela_esperada")
                prompt = (
                    f"Tela/passo '{step_id}'"
                    + (f" — esperada: '{tela}'" if tela else "")
                    + ". Confirma para enviar teclas? (s/n): "
                )
                if not self.confirm_fn(prompt):
                    return ApacStepResult(False, f"operador recusou passo {step_id}")
            else:
                tela = passo.get("tela_esperada")
                if tela:
                    if not self.confirm_fn(
                        f"Tela esperada: '{tela}'. Confirma que está visível? (s/n): "
                    ):
                        return ApacStepResult(
                            False, f"tela inesperada no passo {step_id}"
                        )

            # Sempre refoca o APAC antes de teclas (o "s" do terminal rouba o foco)
            if acao in {
                "press",
                "tecla",
                "type",
                "digitar",
                "texto",
                "hotkey",
                "atalho",
                "salvar",
                "save",
                "foco_janela",
                "focus",
            }:
                if not self.focus_window():
                    return ApacStepResult(False, f"janela perdida no passo {step_id}")
                time.sleep(0.25)

            try:
                self._executar_passo(passo, lanc)
            except KeyboardInterrupt as exc:
                raise ApacInterruptedError(
                    f"Ctrl+C durante passo {step_id}",
                    durante_salvamento=is_save,
                ) from exc

        if parado_antes_salvar or not permitir_salvar:
            return ApacStepResult(
                True,
                "preenchimento enviado; parado antes do salvamento para revisão",
                parado_antes_salvar=True,
            )
        return ApacStepResult(True, "sequência concluída")

    def run_lancamento(self, lanc: Lancamento) -> ApacStepResult:
        """
        Executa passos configuráveis. Na v1, para antes do salvamento
        se permitir_salvar for false ou se não houver passo de salvar mapeado.
        """
        if self.dry_run:
            return self._dry_run(lanc)

        self.assert_live_allowed()
        try:
            if not self.ensure_running():
                return ApacStepResult(False, "janela APAC não ativa")
            self.navegar_ate_cadastro()
        except ApacBlockedError as exc:
            return ApacStepResult(False, str(exc))

        passos: list[dict[str, Any]] = list(self.cfg.apac.get("passos") or [])
        permitir_salvar = bool(self.cfg.apac.get("permitir_salvar", False))
        return self._rodar_sequencia_passos(
            passos, lanc, permitir_salvar=permitir_salvar
        )

    def _dry_run(self, lanc: Lancamento) -> ApacStepResult:
        passos = self.cfg.apac.get("passos") or []
        log.info(
            "[dry-run] identidade=%s numeracao_apac=%s codigo_apac=%s passos_configurados=%s",
            lanc.identidade[:8],
            lanc.numeracao_apac,
            lanc.codigo_apac,
            len(passos),
        )
        if lanc.paciente and lanc.paciente.cpf:
            log.info("[dry-run] CPF disponível no cadastro (não exibido no log).")
        else:
            log.info("[dry-run] CPF ausente — cadastro novo exigiria preenchimento manual.")
        return ApacStepResult(
            True,
            "simulação concluída (nenhuma tecla enviada)",
            parado_antes_salvar=True,
        )

    def _executar_passo(self, passo: dict[str, Any], lanc: Lancamento) -> None:
        pg = self._pg()
        acao = (passo.get("acao") or "").lower()
        if acao in {"foco_janela", "focus"}:
            if not self.focus_window():
                raise ApacBlockedError("falha ao focar janela")
            return
        if acao in {"hotkey", "atalho"}:
            keys = passo.get("teclas") or []
            if not keys:
                raise ApacBlockedError(f"passo {passo} sem teclas")
            pg.hotkey(*keys)
            return
        if acao in {"press", "tecla"}:
            tecla = passo.get("tecla") or passo.get("teclas")
            if not tecla:
                raise ApacBlockedError("passo press sem tecla")
            vezes = int(passo.get("vezes") or 1)
            intervalo = float(passo.get("intervalo_s") or 0)
            if isinstance(tecla, list):
                for t in tecla:
                    pg.press(t)
                return
            for i in range(max(1, vezes)):
                if i > 0 and intervalo > 0:
                    # Refoca entre repetições (console APAC perde Enter se o foco sair)
                    self.focus_window()
                    time.sleep(intervalo)
                log.info("Tecla '%s' (%s/%s)", tecla, i + 1, vezes)
                pg.press(tecla)
            return
        if acao in {"type", "digitar", "texto"}:
            texto = self._resolver_texto(passo, lanc)
            interval = float(passo.get("interval", 0.05))
            pg.write(texto, interval=interval)
            return
        if acao in {"pause", "aguardar"}:
            time.sleep(float(passo.get("segundos", 1)))
            return
        if acao in {"salvar", "save"}:
            teclas = passo.get("teclas") or ["enter"]
            if isinstance(teclas, str):
                pg.press(teclas)
            else:
                pg.hotkey(*teclas) if len(teclas) > 1 else pg.press(teclas[0])
            return
        raise ApacBlockedError(f"acao de passo desconhecida: {acao}")

    def _resolver_texto(self, passo: dict[str, Any], lanc: Lancamento) -> str:
        if "texto" in passo and passo["texto"] is not None:
            return str(passo["texto"])
        campo = (passo.get("campo") or "").lower()
        if campo in {"numeracao", "numero", "número"}:
            return lanc.numeracao_apac
        if campo in {"cpf"}:
            if not lanc.paciente or not lanc.paciente.cpf:
                raise ApacBlockedError("CPF indisponível para digitação")
            # Remove máscara se configurado
            cpf = lanc.paciente.cpf
            if passo.get("somente_digitos", True):
                cpf = "".join(ch for ch in cpf if ch.isdigit())
            return cpf
        if campo in {"codigo", "cod", "procedimento"}:
            return lanc.codigo_apac
        if campo in {"auditor"}:
            return lanc.auditor
        fixos = self.cfg.dados_fixos
        if campo in fixos:
            return str(fixos[campo])
        raise ApacBlockedError(f"campo de texto não resolvido: {campo}")


def _processar_paciente_open_apac(
    automator: ApacAutomator,
    connector,
    lanc: Lancamento,
    *,
    indice: int,
    total: int,
) -> None:
    """
    Fluxo completo: pré-check BIODATA → Insert → identificacao → procedimentos → LISTA.
    Dados incompletos levantam DadosIncompletosError antes de qualquer tecla no APAC.
    """
    log.info(
        "Lote %s/%s: %s | NUMERO APAC: %s (planilha linha %s)",
        indice,
        total,
        lanc.paciente_nome,
        lanc.numeracao_apac,
        lanc.linha_planilha,
    )
    automator._reiniciar_flags_paciente()

    # Pré-check: BIODATA + obrigatorios (CPF/mae/nasc/sexo) antes do Insert
    log.info(
        "Consultando BIODATA para %s (sessao compartilhada do lote)...",
        lanc.paciente_nome,
    )
    cpf = buscar_paciente_biodata(connector, lanc)

    automator.exigir_tela(TelaApac.LISTA, passo=f"antes Insert ({lanc.paciente_nome})")
    automator.iniciar_inclusao_insert()

    # Bloco 1 — cabecalho
    automator.exigir_tela(TelaApac.IDENTIFICACAO, passo="bloco cabecalho")
    automator.exigir_campo_nao_contato(passo="bloco cabecalho")
    automator.preencher_numero_apac(lanc)
    automator.preencher_cnes_unidade(lanc)
    automator.preencher_validade_mes_anterior()
    automator.preencher_tipo_e_nacionalidade()
    automator.preencher_prontuario_e_sem_cpf()

    # Bloco 2 — CPF / nomes
    automator.exigir_tela(TelaApac.IDENTIFICACAO, passo="bloco cpf/nomes")
    automator.preencher_cpf_apac(lanc, cpf)
    automator.preencher_situacao_rua()
    automator.aceitar_nome_se_preenchido(lanc)
    automator.aceitar_nome_mae_se_preenchido(lanc)
    automator.aceitar_nome_responsavel_se_preenchido(lanc)

    # Bloco 3 — endereco
    automator.exigir_tela(TelaApac.IDENTIFICACAO, passo="bloco endereco")
    automator.aceitar_cep_se_preenchido(lanc)
    automator.aceitar_logradouro_se_preenchido(lanc)
    automator.aceitar_endereco_se_preenchido(lanc)
    automator.aceitar_numero_endereco_se_preenchido(lanc)
    automator.aceitar_complemento_se_preenchido(lanc)
    automator.aceitar_bairro_se_preenchido(lanc)

    # Bloco 4 — contato / nascimento / sexo / raca
    automator.exigir_tela(TelaApac.IDENTIFICACAO, passo="bloco contato/raca")
    automator.aceitar_telefone_se_preenchido(lanc)
    automator.aceitar_email_se_preenchido(lanc)
    automator.aceitar_nascimento_se_preenchido(lanc)
    automator.aceitar_sexo_se_preenchido(lanc)
    automator.aceitar_raca_se_preenchido(lanc)
    log.info(
        "APAC: identificacao ate RACA de %s ok — avancando a PROCEDIMENTOS.",
        lanc.paciente_nome,
    )
    automator.avancar_para_procedimentos()
    automator.preencher_cod_procedimento(lanc)
    automator.preencher_cbo()
    automator.preencher_quantidade_procedimento()
    automator.preencher_cns_executante()
    automator.pular_equipe()
    automator.aceitar_servico_se_preenchido()
    automator.aceitar_classificacao_se_preenchido()
    automator.preencher_motivo_saida()
    automator.preencher_data_alta_mes_anterior()
    automator.preencher_cid_dados_complementares()
    automator.preencher_solicitacao_autorizacao()
    log.info(
        "APAC: paciente %s concluido ate LISTA "
        "(cod=%s carater=%s medico_cns=%s (%r) autorizador_cns=%s (%r) orgao=%s).",
        lanc.paciente_nome,
        automator._resolver_codigo_procedimento(lanc),
        automator._dado_fixo("carater_atend", "01") or "01",
        automator._dado_fixo(
            "medico_solicitante_cns", MEDICO_SOLICITANTE_CNS_PADRAO
        ),
        automator._dado_fixo(
            "medico_solicitante_nome", MEDICO_SOLICITANTE_NOME_PADRAO
        ),
        automator._dado_fixo("autorizador_cns", AUTORIZADOR_CNS_PADRAO),
        automator._dado_fixo(
            "autorizador_nome", AUTORIZADOR_NOME_PADRAO
        ),
        automator._dado_fixo("cod_orgao_emiss", "M211130001"),
    )


def _progress_store(cfg: AppConfig) -> ProgressStore:
    return ProgressStore(resolve_path(config_dir(cfg), cfg.progresso_db))


def open_apac_session(cfg: AppConfig) -> None:
    """
    Processa em lote todos os pacientes ativos a partir de paciente_inicio.
    Grava progresso (CONCLUIDO ao voltar a LISTA) para retomar sem reprocessar.
    Sessao APAC + BIODATA abertas uma vez; BIODATA so fecha apos o ultimo
    (ou no finally apos erro bloqueante).
    """
    automator = ApacAutomator(cfg, dry_run=False)
    if not cfg.apac.get("titulo_janela"):
        raise ApacBlockedError("apac.titulo_janela não configurado.")
    try:
        fila_completa = listar_lancamentos_a_partir(cfg)
    except SheetError as exc:
        raise ApacBlockedError(str(exc)) from exc

    store = _progress_store(cfg)
    fila, pulados, alterados = filtrar_pendentes_lote(fila_completa, store)
    for lanc_p, motivo_p in pulados:
        log.info(
            "Pulando %s (%s)",
            lanc_p.paciente_nome,
            motivo_p,
        )
    for lanc_alt in alterados:
        log.warning(
            "Entrada alterada — reprocessando %s",
            lanc_alt.paciente_nome,
        )

    if not fila:
        log.info(
            "Lote open-apac: nada a processar "
            "(%s na planilha a partir do inicio; %s ja pulado(s)).",
            len(fila_completa),
            len(pulados),
        )
        return

    total = len(fila)
    primeiro = fila[0]
    log.info(
        "Lote open-apac: %s pendente(s) de %s a partir de %s (linha %s)",
        total,
        len(fila_completa),
        primeiro.paciente_nome,
        primeiro.linha_planilha,
    )

    automator.garantir_sessao_inicial_limpa()
    automator.ensure_running()
    automator._pausa("pos_apos_ensure")
    automator.exigir_tela(TelaApac.MENU, passo="inicio open-apac")
    automator.navegar_ate_cadastro()

    if automator._confirmar_nav():
        ok = automator.confirm_fn(
            f"Buscar CPF no BIODATA para {total} paciente(s) "
            f"a partir de {primeiro.paciente_nome}? digite s: "
        )
        if not ok:
            raise ApacBlockedError("operador recusou busca de CPF no BIODATA")

    connector = None
    concluidos = 0
    try:
        try:
            connector = build_connector(cfg.sistema_origem, cfg)
        except (BiodataMappingError, ValueError) as exc:
            raise ApacBlockedError(str(exc)) from exc
        automator._biodata_connector = connector

        revisao = 0
        for i, lanc in enumerate(fila, start=1):
            store.upsert(lanc, EstadoLancamento.EM_PROCESSAMENTO)
            try:
                _processar_paciente_open_apac(
                    automator,
                    connector,
                    lanc,
                    indice=i,
                    total=total,
                )
                store.upsert(
                    lanc,
                    EstadoLancamento.CONCLUIDO,
                    motivo="open-apac: voltou a LISTA",
                )
                concluidos += 1
            except DadosIncompletosError as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo=exc.motivo,
                )
                revisao += 1
                log.warning(
                    "Lote: pulando %s/%s (%s) — %s",
                    i,
                    total,
                    lanc.paciente_nome,
                    exc.motivo,
                )
                continue
            except ApacInterruptedError as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.SALVAMENTO_INCERTO
                    if exc.durante_salvamento
                    else EstadoLancamento.ERRO,
                    motivo=str(exc),
                    precisa_reconciliar=exc.durante_salvamento,
                )
                log.error(
                    "Lote interrompido no paciente %s/%s: %s",
                    i,
                    total,
                    lanc.paciente_nome,
                )
                raise
            except ApacBlockedError as exc:
                store.upsert(lanc, EstadoLancamento.ERRO, motivo=str(exc))
                log.error(
                    "Lote interrompido no paciente %s/%s: %s",
                    i,
                    total,
                    lanc.paciente_nome,
                )
                raise
            except KeyboardInterrupt:
                store.upsert(
                    lanc,
                    EstadoLancamento.ERRO,
                    motivo="interrompido pelo usuario (Ctrl+C)",
                )
                log.error(
                    "Lote interrompido (Ctrl+C) no paciente %s/%s: %s",
                    i,
                    total,
                    lanc.paciente_nome,
                )
                raise
            except Exception as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.ERRO,
                    motivo=type(exc).__name__,
                )
                log.error(
                    "Lote interrompido no paciente %s/%s: %s (%s)",
                    i,
                    total,
                    lanc.paciente_nome,
                    type(exc).__name__,
                )
                raise

        log.info(
            "Lote open-apac concluido: %s ok, %s revisao "
            "(%s pulado(s) na retomada).",
            concluidos,
            revisao,
            len(pulados),
        )
    finally:
        automator._biodata_connector = None
        if connector is not None:
            try:
                connector.close()
            except Exception:
                pass


def dump_apac_screen(cfg: AppConfig) -> Path:
    """
    Abre/foca o APAC (conhost), le o buffer e grava em capturas/.
    Retorna o caminho do arquivo salvo.
    """
    automator = ApacAutomator(cfg, dry_run=False)
    if not cfg.apac.get("titulo_janela"):
        raise ApacBlockedError("apac.titulo_janela não configurado.")
    automator.garantir_sessao_inicial_limpa()
    automator.ensure_running()
    automator._pausa("pos_apos_ensure")
    texto = automator.ler_tela_console()
    tela = classificar_tela(texto)
    log.info("dump-apac-screen: classificado como %s", tela.value)
    print("--- buffer APAC ---")
    print(texto)
    print("--- fim ---")
    print(f"classificacao: {tela.value}")

    pasta = Path(cfg.diagnostico.get("pasta_capturas") or "capturas")
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"apac_screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    destino.write_text(
        f"# tela={tela.value}\n{texto}\n",
        encoding="utf-8",
    )
    log.info("Buffer salvo em %s", destino)
    return destino


def _confirm_terminal(prompt: str) -> bool:
    resp = input(prompt).strip().lower()
    if not resp:
        log.warning("Confirmação vazia (só Enter) — digite s para confirmar.")
        return False
    return resp in {"s", "sim", "y", "yes"}
