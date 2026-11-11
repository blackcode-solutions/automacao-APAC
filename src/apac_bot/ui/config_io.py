"""Load/save merge seguro do config.json para a UI (sem apagar chaves alheias)."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Modalidade do fluxo UI (header). Distinto de dados_fixos.tipo_apac (1|3).
MODALIDADE_PADRAO = "padrao"
MODALIDADE_GLAUCOMA = "glaucoma"
MODALIDADES_VALIDAS = frozenset({MODALIDADE_PADRAO, MODALIDADE_GLAUCOMA})
MODALIDADE_LABELS: dict[str, str] = {
    MODALIDADE_PADRAO: "APAC Padrão",
    MODALIDADE_GLAUCOMA: "APAC Glaucoma",
}
MODALIDADES_UI: tuple[str, ...] = tuple(
    MODALIDADE_LABELS[k] for k in (MODALIDADE_PADRAO, MODALIDADE_GLAUCOMA)
)

# Seções da UI agrupadas por tela do APAC Magnético (ordem do fluxo).
UI_SECOES_TELA: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identificação",
        ("cnes_solicitante", "cnes_executante"),
    ),
    # codigo_procedimento vem da coluna COD. na planilha (por paciente).
    (
        "Procedimentos",
        (
            "cbo",
            "cns_executante",
        ),
    ),
    (
        "Solicitação / Autorização",
        (
            "medico_solicitante_cns",
            "medico_solicitante_nome",
        ),
    ),
)

# Seções da APAC Glaucoma (tipo_apac forçado nos ocultos).
# APAC Padrão não exibe codigo_procedimento — vem da coluna COD. da planilha.
UI_SECOES_GLAUCOMA: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Identificação",
        ("cnes_solicitante", "cnes_executante"),
    ),
    (
        "Procedimentos",
        (
            "codigo_procedimento",
            "cbo",
            "cns_executante",
        ),
    ),
    (
        "Solicitação / Autorização",
        (
            "medico_solicitante_cns",
            "medico_solicitante_nome",
        ),
    ),
)

# Valores fixos da APAC Padrão — não aparecem na UI; gravados no save.
DADOS_FIXOS_PADRAO_OCULTOS: dict[str, str] = {
    "tipo_apac": "3",
    "quantidade_procedimento": "1",
    "motivo_saida": "12",
    "carater_atend": "01",
    "cod_orgao_emiss": "M211130001",  # Municipal
}

# Valores fixos da APAC Glaucoma — fora da UI.
DADOS_FIXOS_GLAUCOMA_OCULTOS: dict[str, str] = {
    "tipo_apac": "1",
    "tipo_atendimento": "07",
    "motivo_saida": "15",
    "cod_orgao_emiss": "E210000001",  # Estadual
    "cid_principal": "H401",
}

# Chaves só na UI Glaucoma (persistidas no save; Padrão não exibe o controle).
DADOS_FIXOS_UI_KEYS_GLAUCOMA: tuple[str, ...] = ("codigo_procedimento",)

# Flatten das seções + ocultos + campos com controles especiais fora da grade.
DADOS_FIXOS_UI_KEYS: tuple[str, ...] = (
    tuple(key for _titulo, keys in UI_SECOES_TELA for key in keys)
    + DADOS_FIXOS_UI_KEYS_GLAUCOMA
    + tuple(DADOS_FIXOS_PADRAO_OCULTOS.keys())
    + ("autorizador_cns", "autorizador_nome")
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
    "cod_orgao_emiss": "Código emissor",
    "orgao_emiss_tipo": "Órgão emissor",
}

# Select Municipal/Estadual → código gravado em dados_fixos.
ORGAO_EMISS_POR_TIPO: dict[str, str] = {
    "Municipal": "M211130001",
    "Estadual": "E210000001",
}
ORGAO_EMISS_TIPOS: tuple[str, ...] = tuple(ORGAO_EMISS_POR_TIPO.keys())

CNS_KEYS = frozenset(
    {
        "cns_executante",
        "medico_solicitante_cns",
        "autorizador_cns",
    }
)

# Catálogo UI (ampliar à mão quando houver novos sistemas/clínicas).
SISTEMAS_UI: tuple[str, ...] = ("BIODATA", "EYECARE", "SISAC")
CLINICAS_POR_SISTEMA: dict[str, tuple[str, ...]] = {
    "biodata": ("oftalmocentro91",),
    "eyecare": ("IMO",),
    "sisac": (),
}
SISTEMAS_ORIGEM_VALIDOS = frozenset(CLINICAS_POR_SISTEMA.keys())

CLINICA_PADRAO_POR_SISTEMA: dict[str, str] = {
    "biodata": "oftalmocentro91",
    "eyecare": "IMO",
}

SISTEMA_POR_CLINICA: dict[str, str] = {
    "oftalmocentro91": "biodata",
    "IMO": "eyecare",
}

CLINICAS_UI: tuple[str, ...] = tuple(
    cid
    for sistema in ("biodata", "eyecare")
    for cid in (CLINICAS_POR_SISTEMA.get(sistema) or ())
)

# Defaults de CNES por clínica (ampliar à mão).
CNES_POR_CLINICA: dict[str, dict[str, str]] = {
    "oftalmocentro91": {
        "cnes_solicitante": "6618839",
        "cnes_executante": "6618839",
    },
    "IMO": {
        "cnes_solicitante": "9398392",
        "cnes_executante": "9398392",
    },
}

CNES_UI_KEYS: tuple[str, ...] = ("cnes_solicitante", "cnes_executante")

# Defaults do bloco planilha_prontuarios quando a UI cria o caminho pela 1ª vez.
PLANILHA_PRONTUARIOS_DEFAULTS: dict[str, Any] = {
    "aba": "APAC ",
    "linha_cabecalho": 3,
    "colunas": {
        "PRONTUARIO": "Prontuário",
        "CLIENTE": "Cliente",
        "CODIGO": "Código",
        "HONOR": "Honor($)",
        "QTD": "Qtd",
    },
}

PLANILHA_PACIENTES_DEFAULTS: dict[str, Any] = {
    "linha_cabecalho": 1,
    "colunas": {
        "PRONTUARIO": "prontuários",
        "PACIENTE": "paciente",
        "CPF": "cpf",
        "NASCIMENTO": "data_nascimento",
        "GENERO": "genero",
        "CEP": "cep",
        "ENDERECO": "endereço",
        "NUMERO": "numero",
        "COMPLEMENTO": "complemento",
        "BAIRRO": "bairro",
        "NOME_MAE": "nome da mae",
    },
}

def normalizar_sistema_origem(valor: str) -> str:
    key = str(valor or "").strip().lower()
    if key == "icare":
        return "eyecare"
    return key


def normalizar_modalidade(valor: str) -> str:
    key = str(valor or "").strip().lower()
    if key in MODALIDADES_VALIDAS:
        return key
    # Labels da UI → código canônico.
    for codigo, label in MODALIDADE_LABELS.items():
        if label.lower() == str(valor or "").strip().lower():
            return codigo
    return MODALIDADE_PADRAO


def modalidade_ui_label(modalidade: str) -> str:
    return MODALIDADE_LABELS.get(
        normalizar_modalidade(modalidade), MODALIDADE_LABELS[MODALIDADE_PADRAO]
    )


def secoes_para_modalidade(
    modalidade: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if normalizar_modalidade(modalidade) == MODALIDADE_GLAUCOMA:
        return UI_SECOES_GLAUCOMA
    return UI_SECOES_TELA


def aplicar_defaults_clinica(clinica_id: str) -> dict[str, str]:
    """Retorna CNES (e futuros defaults) da clínica, ou {} se desconhecida."""
    key = str(clinica_id or "").strip()
    bloco = CNES_POR_CLINICA.get(key) or {}
    return {k: str(bloco.get(k) or "").strip() for k in CNES_UI_KEYS if bloco.get(k)}


def codigo_orgao_emiss(tipo: str) -> str:
    """Código APAC a partir do tipo Municipal/Estadual (default Municipal)."""
    key = str(tipo or "").strip()
    return ORGAO_EMISS_POR_TIPO.get(key) or ORGAO_EMISS_POR_TIPO["Municipal"]


def tipo_orgao_emiss(codigo: str) -> str:
    """Tipo do select a partir do código gravado (default Municipal)."""
    valor = str(codigo or "").strip()
    for tipo, cod in ORGAO_EMISS_POR_TIPO.items():
        if cod == valor:
            return tipo
    return "Municipal"


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
    planilha_prontuarios_caminho: str = ""
    planilha_pacientes_caminho: str = ""
    planilha_aba_glaucoma: str = ""
    paciente_inicio: str = ""
    modalidade: str = MODALIDADE_PADRAO
    dados_fixos: dict[str, str] = field(default_factory=dict)

    def dados_fixos_completos(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in DADOS_FIXOS_UI_KEYS:
            out[key] = str(self.dados_fixos.get(key, "") or "").strip()
        modalidade = normalizar_modalidade(self.modalidade)
        if modalidade == MODALIDADE_PADRAO:
            # quantidade / motivo saída / caráter sempre fixos.
            out.update(DADOS_FIXOS_PADRAO_OCULTOS)
        elif modalidade == MODALIDADE_GLAUCOMA:
            # Ocultos do Padrão + overrides Glaucoma (tipo_apac=1, tipate=07).
            out.update(DADOS_FIXOS_PADRAO_OCULTOS)
            out.update(DADOS_FIXOS_GLAUCOMA_OCULTOS)
        return out


class ConfigIoError(Exception):
    pass


def default_config_path() -> Path:
    from apac_bot.runtime_paths import app_dir

    return app_dir() / "config.json"


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
    prontuarios = raw.get("planilha_prontuarios") or {}
    glaucoma = raw.get("planilha_glaucoma") or {}
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
    sistema_por_clinica = SISTEMA_POR_CLINICA.get(clinica)
    if sistema_por_clinica and sistema_por_clinica != sistema:
        sistema = sistema_por_clinica
        clinicas = CLINICAS_POR_SISTEMA.get(sistema) or ()
    if clinica and clinicas and clinica not in clinicas:
        clinica = (
            CLINICA_PADRAO_POR_SISTEMA.get(sistema, "")
            if len(clinicas) == 1
            else ""
        )
    elif not clinica and clinicas:
        clinica = CLINICA_PADRAO_POR_SISTEMA.get(sistema, clinicas[0])
    pacientes = raw.get("planilha_pacientes") or {}
    modalidade = normalizar_modalidade(str(apac.get("modalidade") or ""))
    planilha_caminho = str(planilha.get("caminho") or "").strip()
    # Legado dual: Relatório em planilha_glaucoma → usa como planilha.caminho.
    if modalidade == MODALIDADE_GLAUCOMA and not planilha_caminho:
        legado = str(glaucoma.get("caminho") or "").strip()
        if legado:
            planilha_caminho = legado
    return UiFormData(
        sistema_origem=sistema,
        clinica_id=clinica,
        planilha_caminho=planilha_caminho,
        planilha_prontuarios_caminho=str(prontuarios.get("caminho") or "").strip(),
        planilha_pacientes_caminho=str(pacientes.get("caminho") or "").strip(),
        planilha_aba_glaucoma=str(planilha.get("aba_glaucoma") or "").strip(),
        paciente_inicio=str(apac.get("paciente_inicio") or "").strip(),
        modalidade=modalidade,
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
        erros.append("Sistema deve ser BIODATA, EYECARE ou SISAC.")
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
    modalidade = normalizar_modalidade(form.modalidade)
    if (
        modalidade != MODALIDADE_GLAUCOMA
        and sistema != "eyecare"
        and not form.planilha_prontuarios_caminho.strip()
    ):
        erros.append("Caminho da planilha de prontuários é obrigatório.")
    if sistema == "eyecare" and not form.planilha_pacientes_caminho.strip():
        erros.append("Caminho da planilha de pacientes é obrigatório para EYECARE.")

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
    modalidade = normalizar_modalidade(form.modalidade)
    if modalidade == MODALIDADE_GLAUCOMA:
        planilha["aba_glaucoma"] = form.planilha_aba_glaucoma.strip()
    out["planilha"] = planilha

    # Bloco dual antigo deixa de ser usado; remove path órfão no save Glaucoma.
    if modalidade == MODALIDADE_GLAUCOMA and "planilha_glaucoma" in out:
        out.pop("planilha_glaucoma", None)

    prontuarios = dict(out.get("planilha_prontuarios") or {})
    if not prontuarios:
        prontuarios = deepcopy(PLANILHA_PRONTUARIOS_DEFAULTS)
    else:
        for key, valor in PLANILHA_PRONTUARIOS_DEFAULTS.items():
            if key == "colunas":
                cols = dict(prontuarios.get("colunas") or {})
                for ck, cv in valor.items():
                    cols.setdefault(ck, cv)
                prontuarios["colunas"] = cols
            else:
                prontuarios.setdefault(key, valor)
    caminho_pront = form.planilha_prontuarios_caminho.strip()
    # Glaucoma/ICARE: UI sem anexo de prontuários — não zerar path salvo no JSON.
    preservar_pront_vazio = (
        not caminho_pront
        and str(prontuarios.get("caminho") or "").strip()
        and (
            modalidade == MODALIDADE_GLAUCOMA
            or sistema == "eyecare"
        )
    )
    if not preservar_pront_vazio:
        prontuarios["caminho"] = caminho_pront
    out["planilha_prontuarios"] = prontuarios

    pacientes = dict(out.get("planilha_pacientes") or {})
    if not pacientes:
        pacientes = deepcopy(PLANILHA_PACIENTES_DEFAULTS)
    else:
        for key, valor in PLANILHA_PACIENTES_DEFAULTS.items():
            if key == "colunas":
                cols = dict(pacientes.get("colunas") or {})
                for ck, cv in valor.items():
                    cols.setdefault(ck, cv)
                pacientes["colunas"] = cols
            else:
                pacientes.setdefault(key, valor)
    pacientes["caminho"] = form.planilha_pacientes_caminho.strip()
    out["planilha_pacientes"] = pacientes

    from apac_bot.icare_faturamento_sheet import (
        PLANILHA_ICARE_FATURAMENTO_DEFAULTS,
    )

    icare_fat = dict(out.get("planilha_icare_faturamento") or {})
    if not icare_fat:
        icare_fat = deepcopy(PLANILHA_ICARE_FATURAMENTO_DEFAULTS)
    else:
        for key, valor in PLANILHA_ICARE_FATURAMENTO_DEFAULTS.items():
            if key == "colunas":
                cols = dict(icare_fat.get("colunas") or {})
                for ck, cv in valor.items():
                    cols.setdefault(ck, cv)
                icare_fat["colunas"] = cols
            else:
                icare_fat.setdefault(key, valor)
    out["planilha_icare_faturamento"] = icare_fat

    apac = dict(out.get("apac") or {})
    apac["paciente_inicio"] = form.paciente_inicio.strip()
    apac["modalidade"] = modalidade
    out["apac"] = apac

    fixos = dict(out.get("dados_fixos") or {})
    for key, valor in form.dados_fixos_completos().items():
        if key in CNS_KEYS:
            fixos[key] = _cns_digitos(valor)
        else:
            fixos[key] = valor
    out["dados_fixos"] = fixos

    # Bloco licenca (server_url / license_key) não é editado pelo form principal.
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


def save_modalidade(path: Path, modalidade: str) -> str:
    """
    Grava só apac.modalidade (sem validar o restante do formulário).
    Permite persistir a troca Padrão/Glaucoma mesmo com Glaucoma incompleto.
    """
    if not path.is_file():
        raise ConfigIoError(f"Arquivo de configuração não encontrado: {path}")
    raw = load_raw(path)
    codigo = normalizar_modalidade(modalidade)
    apac = dict(raw.get("apac") or {})
    apac["modalidade"] = codigo
    raw["apac"] = apac
    path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return codigo


def save_license_key(path: Path, license_key: str) -> str:
    """
    Grava só licenca.license_key (tela de ativação).
    Preserva server_url / grace_dias; não valida o formulário principal.
    """
    if not path.is_file():
        raise ConfigIoError(f"Arquivo de configuração não encontrado: {path}")
    key = str(license_key or "").strip()
    if not key:
        raise ConfigIoError("Informe a chave de licença.")
    raw = load_raw(path)
    licenca = dict(raw.get("licenca") or {})
    licenca["license_key"] = key
    licenca.setdefault("server_url", "")
    licenca.setdefault("grace_dias", 14)
    raw["licenca"] = licenca
    path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return key


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
