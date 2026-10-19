from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# Campos do formulário / diálogo de pesquisa necessários para consulta real
REQUIRED_BIODATA_LOCATORS = (
    "campo_busca_nome",
    "opcao_resultado",
    "botao_confirmar_pesquisa",
    "botao_pesquisar",
    "campo_cpf",
    "campo_nome",
    "campo_id_paciente",
)

# Navegação home -> Cadastro de Pacientes
REQUIRED_BIODATA_NAV = (
    "modulo_atendimento",
    "campo_busca_menu",
    "item_cadastro_pacientes",
)

REQUIRED_COLUMN_KEYS = ("PACIENTE", "COD", "AUDITOR", "NUMERACAO")


class ConfigError(Exception):
    pass


@dataclass
class AppConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def clinica_id(self) -> str:
        return str(self.raw["clinica_id"])

    @property
    def sistema_origem(self) -> str:
        return str(self.raw.get("sistema_origem", "mock")).lower()

    @property
    def planilha_caminho(self) -> Path:
        return Path(self.raw["planilha"]["caminho"])

    @property
    def planilha_aba(self) -> str:
        return str(self.raw["planilha"]["aba"])

    @property
    def planilha_linha_cabecalho(self) -> int:
        raw = (self.raw.get("planilha") or {}).get("linha_cabecalho", 1)
        try:
            linha = int(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigError("planilha.linha_cabecalho deve ser um inteiro >= 1.") from exc
        if linha < 1:
            raise ConfigError("planilha.linha_cabecalho deve ser >= 1.")
        return linha

    @property
    def planilha_apenas_ativos(self) -> bool:
        """Se True, ignora linhas ocultas pelo filtro do Excel (ativos = visíveis)."""
        raw = (self.raw.get("planilha") or {}).get("apenas_ativos", True)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "sim", "yes"}
        return bool(raw)

    @property
    def colunas(self) -> dict[str, str]:
        return dict(self.raw["planilha"]["colunas"])

    @property
    def planilha_prontuarios(self) -> dict[str, Any]:
        """Config da 2a planilha (Cliente/Prontuario) para desambiguacao BIODATA."""
        return dict(self.raw.get("planilha_prontuarios") or {})

    @property
    def normalizacao(self) -> dict[str, Any]:
        return dict(self.raw.get("normalizacao") or {})

    @property
    def dados_fixos(self) -> dict[str, Any]:
        return dict(self.raw.get("dados_fixos") or {})

    @property
    def biodata(self) -> dict[str, Any]:
        return dict(self.raw.get("biodata") or {})

    @property
    def apac(self) -> dict[str, Any]:
        return dict(self.raw.get("apac") or {})

    @property
    def export_set(self) -> dict[str, Any]:
        """Config do gerador de arquivo .SET (layout INTERNO)."""
        return dict(self.raw.get("export_set") or {})

    @property
    def timeouts(self) -> dict[str, Any]:
        return dict(self.raw.get("timeouts") or {})

    @property
    def progresso_db(self) -> Path:
        prog = self.raw.get("progresso") or {}
        return Path(prog.get("caminho_db", "data/progress.db"))

    @property
    def diagnostico(self) -> dict[str, Any]:
        return dict(self.raw.get("diagnostico") or {})

    def with_planilha(self, caminho: str | Path) -> "AppConfig":
        novo = dict(self.raw)
        planilha = dict(novo.get("planilha") or {})
        planilha["caminho"] = str(caminho)
        novo["planilha"] = planilha
        return AppConfig(raw=novo, path=self.path)


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"Arquivo de configuração não encontrado: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON inválido em {p}: {exc}") from exc
    cfg = AppConfig(raw=raw, path=p)
    validate_config(cfg, for_live=False, for_biodata_real=False)
    return cfg


def biodata_modo(cfg: AppConfig) -> str:
    """
    Resolve biodata.modo: 'api' | 'browser'.
    Default 'api' se existir biodata.api.base_url; senão 'browser'.
    """
    biodata = cfg.biodata
    raw = str(biodata.get("modo") or "").strip().lower()
    if raw in {"api", "browser"}:
        return raw
    api = biodata.get("api") or {}
    if str(api.get("base_url") or "").strip():
        return "api"
    return "browser"


def validate_config(
    cfg: AppConfig,
    *,
    for_live: bool = False,
    for_biodata_real: bool = False,
) -> list[str]:
    """Valida configuração. Retorna avisos; levanta ConfigError em erros fatais."""
    erros: list[str] = []
    avisos: list[str] = []

    if not cfg.raw.get("clinica_id"):
        erros.append("clinica_id é obrigatório.")

    origem = cfg.sistema_origem
    if origem not in {"mock", "biodata"}:
        erros.append("sistema_origem deve ser 'mock' ou 'biodata'.")

    planilha = cfg.raw.get("planilha") or {}
    if not planilha.get("caminho"):
        erros.append("planilha.caminho é obrigatório.")
    if not planilha.get("aba"):
        erros.append("planilha.aba é obrigatória.")

    colunas = planilha.get("colunas") or {}
    for key in REQUIRED_COLUMN_KEYS:
        if key not in colunas or not colunas[key]:
            erros.append(f"planilha.colunas.{key} é obrigatório.")

    if origem == "biodata":
        pront = cfg.raw.get("planilha_prontuarios") or {}
        if not str(pront.get("caminho") or "").strip():
            erros.append(
                "planilha_prontuarios.caminho é obrigatório quando "
                "sistema_origem=biodata."
            )

    precisa_biodata = for_biodata_real or (origem == "biodata" and for_live)
    if precisa_biodata:
        modo = biodata_modo(cfg)
        if modo == "api":
            api = cfg.biodata.get("api") or {}
            if not str(api.get("base_url") or "").strip():
                erros.append("biodata.api.base_url é obrigatório no modo API.")
            id_sac = api.get("id_sac")
            if id_sac is None or str(id_sac).strip() == "":
                erros.append("biodata.api.id_sac é obrigatório no modo API.")
            from apac_bot.secrets import SecretsError, load_biodata_credentials

            try:
                creds = load_biodata_credentials(cfg)
            except SecretsError as exc:
                erros.append(f"Credenciais BIODATA inválidas: {exc}")
            else:
                if creds is None:
                    erros.append(
                        "Modo API exige secrets.local.json com usuario e senha."
                    )
        else:
            missing = biodata_locators_pendentes(cfg)
            if missing:
                erros.append(
                    "Localizadores BIODATA incompletos (consulta real bloqueada): "
                    + ", ".join(missing)
                )
            if not (cfg.biodata.get("url")):
                erros.append("biodata.url é obrigatório para consulta real.")

    if for_live:
        apac = cfg.apac
        passos = apac.get("passos") or []
        minimos = apac.get("passos_minimos_para_live") or []
        nomes = {p.get("id") or p.get("acao") for p in passos if isinstance(p, dict)}
        faltando = [m for m in minimos if m not in nomes]
        if not passos:
            erros.append(
                "apac.passos está vazio — execução live bloqueada até mapear a sequência."
            )
        elif faltando:
            erros.append(
                "Passos APAC mínimos ausentes para live: " + ", ".join(faltando)
            )
        if not apac.get("titulo_janela"):
            erros.append("apac.titulo_janela é obrigatório para live.")

    if erros:
        raise ConfigError("\n".join(erros))
    return avisos


def biodata_locators_pendentes(cfg: AppConfig) -> list[str]:
    locators = (cfg.biodata.get("locators") or {})
    navegacao = (cfg.biodata.get("navegacao") or {})
    pendentes = []
    for key in REQUIRED_BIODATA_NAV:
        val = navegacao.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            pendentes.append(f"navegacao.{key}")
    for key in REQUIRED_BIODATA_LOCATORS:
        val = locators.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            pendentes.append(key)
    return pendentes


def apac_pronto_para_live(cfg: AppConfig) -> bool:
    try:
        validate_config(cfg, for_live=True, for_biodata_real=False)
        return True
    except ConfigError:
        return False


def resolve_path(base: Path, maybe_relative: Path) -> Path:
    if maybe_relative.is_absolute():
        return maybe_relative
    return (base / maybe_relative).resolve()


def config_dir(cfg: AppConfig) -> Path:
    return cfg.path.parent.resolve()
