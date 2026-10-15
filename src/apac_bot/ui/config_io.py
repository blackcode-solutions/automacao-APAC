"""Load/save merge seguro do config.json para a UI (sem apagar chaves alheias)."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Seções da UI agrupadas por tela do APAC Magnético (ordem do fluxo).
UI_SECOES_TELA: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identificação",
        ("cnes_solicitante", "cnes_executante", "tipo_apac"),
    ),
    (
        "Procedimentos",
        (
            "codigo_procedimento",
            "cbo",
            "quantidade_procedimento",
            "cns_executante",
            "motivo_saida",
        ),
    ),
    (
        "Solicitação / Autorização",
        (
            "carater_atend",
            "medico_solicitante_cns",
            "medico_solicitante_nome",
            "autorizador_cns",
            "autorizador_nome",
            "cod_orgao_emiss",
        ),
    ),
)

# Flatten das seções (ordem estável para collect/validate/merge).
DADOS_FIXOS_UI_KEYS: tuple[str, ...] = tuple(
    key for _titulo, keys in UI_SECOES_TELA for key in keys
)

# Labels amigáveis (UI).
DADOS_FIXOS_LABELS: dict[str, str] = {
    "cnes_solicitante": "CNES solicitante",
    "cnes_executante": "CNES executante",
    "tipo_apac": "Tipo APAC",
    "codigo_procedimento": "Código procedimento",
    "cbo": "CBO",
    "quantidade_procedimento": "Quantidade",
    "cns_executante": "CNS executante",
    "motivo_saida": "Motivo saída",
    "carater_atend": "Caráter atendimento",
    "medico_solicitante_cns": "CNS médico solicitante",
    "medico_solicitante_nome": "Nome médico solicitante",
    "autorizador_cns": "CNS autorizador",
    "autorizador_nome": "Nome autorizador",
    "cod_orgao_emiss": "Código órgão emissor",
}

CNS_KEYS = frozenset(
    {
        "cns_executante",
        "medico_solicitante_cns",
        "autorizador_cns",
    }
)

# Catálogo UI (ampliar à mão quando houver novos sistemas/clínicas).
SISTEMAS_UI: tuple[str, ...] = ("BIODATA", "SISAC")
CLINICAS_POR_SISTEMA: dict[str, tuple[str, ...]] = {
    "biodata": ("oftalmocentro91",),
    "sisac": (),
}
SISTEMAS_ORIGEM_VALIDOS = frozenset(CLINICAS_POR_SISTEMA.keys())

# Defaults de CNES por clínica (ampliar à mão).
CNES_POR_CLINICA: dict[str, dict[str, str]] = {
    "oftalmocentro91": {
        "cnes_solicitante": "6618839",
        "cnes_executante": "6618839",
    },
}

CNES_UI_KEYS: tuple[str, ...] = ("cnes_solicitante", "cnes_executante")


def normalizar_sistema_origem(valor: str) -> str:
    return str(valor or "").strip().lower()


def aplicar_defaults_clinica(clinica_id: str) -> dict[str, str]:
    """Retorna CNES (e futuros defaults) da clínica, ou {} se desconhecida."""
    key = str(clinica_id or "").strip()
    bloco = CNES_POR_CLINICA.get(key) or {}
    return {k: str(bloco.get(k) or "").strip() for k in CNES_UI_KEYS if bloco.get(k)}


def sistema_ui_label(sistema_origem: str) -> str:
    key = normalizar_sistema_origem(sistema_origem)
    for label in SISTEMAS_UI:
        if label.lower() == key:
            return label
    return SISTEMAS_UI[0]


@dataclass
class UiFormData:
    sistema_origem: str = "biodata"
    clinica_id: str = ""
    planilha_caminho: str = ""
    paciente_inicio: str = ""
    dados_fixos: dict[str, str] = field(default_factory=dict)

    def dados_fixos_completos(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in DADOS_FIXOS_UI_KEYS:
            out[key] = str(self.dados_fixos.get(key, "") or "").strip()
        return out


class ConfigIoError(Exception):
    pass


def default_config_path() -> Path:
    return Path.cwd() / "config.json"


def load_raw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigIoError(f"Arquivo de configuração não encontrado: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigIoError(f"JSON inválido em {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigIoError(f"Config inválida em {path}: raiz deve ser objeto.")
    return raw


def form_from_raw(raw: dict[str, Any]) -> UiFormData:
    planilha = raw.get("planilha") or {}
    apac = raw.get("apac") or {}
    fixos = raw.get("dados_fixos") or {}
    dados: dict[str, str] = {}
    for key in DADOS_FIXOS_UI_KEYS:
        dados[key] = str(fixos.get(key, "") or "").strip()
    sistema = normalizar_sistema_origem(str(raw.get("sistema_origem") or "biodata"))
    if sistema not in SISTEMAS_ORIGEM_VALIDOS:
        sistema = "biodata"
    clinica = str(raw.get("clinica_id") or "").strip()
    clinicas = CLINICAS_POR_SISTEMA.get(sistema) or ()
    if sistema == "biodata" and clinicas:
        clinica = clinicas[0]
    elif clinica and clinicas and clinica not in clinicas:
        clinica = clinicas[0] if len(clinicas) == 1 else ""
    return UiFormData(
        sistema_origem=sistema,
        clinica_id=clinica,
        planilha_caminho=str(planilha.get("caminho") or "").strip(),
        paciente_inicio=str(apac.get("paciente_inicio") or "").strip(),
        dados_fixos=dados,
    )


def load_form(path: Path) -> UiFormData:
    return form_from_raw(load_raw(path))


def _cns_digitos(valor: str) -> str:
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def validate_form(form: UiFormData) -> list[str]:
    """Validação leve da UI. Retorna lista de erros (vazia = ok)."""
    erros: list[str] = []
    sistema = normalizar_sistema_origem(form.sistema_origem)
    if sistema not in SISTEMAS_ORIGEM_VALIDOS:
        erros.append("Sistema deve ser BIODATA ou SISAC.")
    clinicas = CLINICAS_POR_SISTEMA.get(sistema) or ()
    clinica = form.clinica_id.strip()
    if clinicas:
        if not clinica:
            erros.append("ID da clínica é obrigatório.")
        elif clinica not in clinicas:
            erros.append(
                f"ID da clínica inválido para {sistema_ui_label(sistema)}."
            )
    elif not clinica:
        erros.append(
            f"Nenhuma clínica cadastrada para {sistema_ui_label(sistema) or sistema}."
        )
    if not form.planilha_caminho.strip():
        erros.append("Caminho da planilha é obrigatório.")

    fixos = form.dados_fixos_completos()
    for chave in ("cnes_solicitante", "cnes_executante"):
        if not fixos.get(chave):
            erros.append(f"{DADOS_FIXOS_LABELS[chave]} é obrigatório.")

    tipo = fixos.get("tipo_apac", "")
    if tipo not in {"1", "3"}:
        erros.append("Tipo APAC deve ser 1 ou 3.")

    for chave in CNS_KEYS:
        digitos = _cns_digitos(fixos.get(chave, ""))
        if not digitos:
            erros.append(f"{DADOS_FIXOS_LABELS[chave]} é obrigatório.")
        elif len(digitos) != 15:
            erros.append(
                f"{DADOS_FIXOS_LABELS[chave]} deve ter 15 dígitos "
                f"(encontrados {len(digitos)})."
            )

    if not fixos.get("cod_orgao_emiss"):
        erros.append(f"{DADOS_FIXOS_LABELS['cod_orgao_emiss']} é obrigatório.")

    return erros


def merge_form_into_raw(raw: dict[str, Any], form: UiFormData) -> dict[str, Any]:
    """
    Copia profunda do raw e aplica só campos da UI.
    Preserva biodata, apac restante, timeouts, etc.
    """
    out = deepcopy(raw)
    sistema = normalizar_sistema_origem(form.sistema_origem)
    if sistema not in SISTEMAS_ORIGEM_VALIDOS:
        sistema = "biodata"
    out["sistema_origem"] = sistema
    out["clinica_id"] = form.clinica_id.strip()

    planilha = dict(out.get("planilha") or {})
    planilha["caminho"] = form.planilha_caminho.strip()
    out["planilha"] = planilha

    apac = dict(out.get("apac") or {})
    apac["paciente_inicio"] = form.paciente_inicio.strip()
    out["apac"] = apac

    fixos = dict(out.get("dados_fixos") or {})
    for key, valor in form.dados_fixos_completos().items():
        if key in CNS_KEYS:
            fixos[key] = _cns_digitos(valor)
        else:
            fixos[key] = valor
    out["dados_fixos"] = fixos
    return out


def save_form(
    path: Path,
    form: UiFormData,
    *,
    base_raw: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Valida, faz merge e grava JSON.
    Se o arquivo não existir e base_raw for passado, usa base_raw como partida.
    """
    erros = validate_form(form)
    if erros:
        raise ConfigIoError("\n".join(erros))

    if path.is_file():
        raw = load_raw(path)
    elif base_raw is not None:
        raw = deepcopy(base_raw)
    else:
        raise ConfigIoError(
            f"Arquivo de configuração não encontrado: {path}. "
            "Copie config.example.json para config.json antes."
        )

    merged = merge_form_into_raw(raw, form)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return merged


def secrets_missing(config_path: Path) -> bool:
    """True se secrets.local.json (ou o configurado) não existir / sem senha."""
    try:
        raw = load_raw(config_path)
    except ConfigIoError:
        return True
    biodata = raw.get("biodata") or {}
    secrets_rel = biodata.get("secrets_file") or "secrets.local.json"
    secrets_path = (config_path.parent / secrets_rel).resolve()
    if not secrets_path.is_file():
        return True
    try:
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict):
        return True
    return not str(data.get("senha") or data.get("password") or "").strip()
