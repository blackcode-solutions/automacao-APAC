from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

_MESES_NOME: dict[str, int] = {}
for _num, _mes in enumerate(
    (
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ),
    1,
):
    _MESES_NOME[_mes] = _num
for _num, _en in enumerate(
    (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ),
    1,
):
    _MESES_NOME[_en] = _num
# «março» após remoção de acento vira «marco» (já em _MESES_NOME).
_MESES_NOME["março"] = 3
_MESES_NOME["mar"] = 3
_MESES_NOME["sep"] = 9
_MESES_NOME["oct"] = 10
_MESES_NOME["nov"] = 11
_MESES_NOME["dec"] = 12

_RE_MES_DIA_ANO = re.compile(
    r"^\s*([a-zà-ú]+)\s+(\d{1,2}),?\s+(\d{4})\s*$",
    re.IGNORECASE,
)
_RE_DIA_DE_MES = re.compile(
    r"^\s*(\d{1,2})\s+de\s+([a-zà-ú]+)\s+de\s+(\d{4})\s*$",
    re.IGNORECASE,
)

from apac_bot.tipos_logradouro import tipos_logradouro_por_tamanho


def ymd_valido(ano: int, mes: int, dia: int) -> bool:
    """True se data de calendário válida e ano plausível para nascimento (1900–2100)."""
    if ano < 1900 or ano > 2100:
        return False
    try:
        date(ano, mes, dia)
        return True
    except ValueError:
        return False


def cell_as_text(value: Any) -> str:
    """Preserva identificadores como texto, incluindo zeros à esquerda."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Evita "123.0" quando a planilha armazenou número
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    return text


def normalize_numeracao(original: str, regras: dict[str, Any]) -> str:
    """Aplica apenas regras explicitamente configuradas; preserva o original à parte."""
    valor = original
    if regras.get("hifen_para_barra"):
        # Converte apenas o hífen antes do último dígito (padrão planilha → APAC)
        if "-" in valor:
            partes = valor.rsplit("-", 1)
            if len(partes) == 2 and partes[1]:
                valor = f"{partes[0]}/{partes[1]}"
    return valor


def normalize_codigo(original: str, regras: dict[str, Any]) -> str:
    valor = original
    zeros = regras.get("preencher_zeros_esquerda")
    if zeros is not None:
        try:
            largura = int(zeros)
        except (TypeError, ValueError):
            return valor
        if largura > 0 and valor.isdigit():
            valor = valor.zfill(largura)
    return valor


def optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = cell_as_text(value)
    return text if text else None


# Fallback único quando BIODATA não tem CEP válido (SET e Magnético).
CEP_PADRAO_APAC = "65010000"
CEPS_INVALIDOS_APAC = frozenset({
    "65000000",
    "65056500",
    "65050152",
    "65099135",
    "65058210",
    "65058000",
    "65034540",
    "65055845",
    "65063685",
    "65080140",
    "65100000",
    "65055485",
})

# CEPs conhecidos (BIODATA) remapeados para outro válido — não usam CEP_PADRAO_APAC.
CEP_SUBSTITUICOES_APAC: dict[str, str] = {
    "65040084": "65763000",
    "65042357": "65763000",
    "65095886": "65763000",
    "65052120": "65763000",
    "66666666": "65763000",
}


def cep_para_apac(valor: Optional[str]) -> str:
    """
    CEP de 8 dígitos da origem; substituições em CEP_SUBSTITUICOES_APAC;
    inválidos genéricos → CEP_PADRAO_APAC; ausente/curto → CEP_PADRAO_APAC.
    """
    digitos = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(digitos) >= 8:
        cep = digitos[:8]
        substituto = CEP_SUBSTITUICOES_APAC.get(cep)
        if substituto is not None:
            return substituto
        if cep in CEPS_INVALIDOS_APAC:
            return CEP_PADRAO_APAC
        return cep
    return CEP_PADRAO_APAC


def cpf_digitos(value: Optional[str]) -> str:
    """Retorna só dígitos do CPF (vazio se inválido/ausente)."""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def tem_cpf_valido(value: Optional[str]) -> bool:
    """True se houver 11 dígitos após limpar máscara."""
    return len(cpf_digitos(value)) == 11


def cns_digitos(value: Optional[str]) -> str:
    """Retorna só dígitos do CNS (vazio se ausente)."""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def tem_cns_valido(value: Optional[str]) -> bool:
    """True se houver 15 dígitos após limpar máscara (campo layout INTERNO)."""
    return len(cns_digitos(value)) == 15


def identidade_paciente_set(
    cpf: Optional[str], cns: Optional[str]
) -> tuple[str, str]:
    """
    CPF e CNS do paciente são mutuamente exclusivos no SET.
    Prioridade CPF: se válido, CNS sai vazio; senão, usa CNS se válido.
    """
    if tem_cpf_valido(cpf):
        return cpf_digitos(cpf), ""
    if tem_cns_valido(cns):
        return "", cns_digitos(cns)
    return "", ""


def sexo_para_apac(value: Optional[str]) -> Optional[str]:
    """Normaliza sexo da origem para M ou F (APAC)."""
    if not value:
        return None
    v = str(value).strip().upper()
    if v in {"M", "F"}:
        return v
    if "MASC" in v or v in {"1", "MASCULINO"}:
        return "M"
    if "FEM" in v or v in {"2", "FEMININO"}:
        return "F"
    if v.startswith("M"):
        return "M"
    if v.startswith("F"):
        return "F"
    return None


_PRIMEIRO_NOME_MIN = 3

# Heurística Eyecare: não substitui cadastro oficial; só preenche quando genero vazio.
_PRIMEIRO_NOME_FEMININO = frozenset(
    {
        "ANA",
        "BEATRIZ",
        "HELENA",
        "JULIA",
        "LUCIA",
        "MARIA",
        "PAULA",
        "RITA",
        "SANDRA",
        "TERESA",
    }
)
_PRIMEIRO_NOME_MASCULINO = frozenset(
    {
        "ANTONIO",
        "CARLOS",
        "JOAO",
        "JOSE",
        "JORGE",
        "LUIS",
        "MARCOS",
        "MARIO",
        "PAULO",
        "PEDRO",
        "SERGIO",
    }
)
_PRIMEIRO_NOME_AMBIGUO = frozenset(
    {
        "ANDRE",
        "CRIS",
        "DANIEL",
        "DARIO",
        "FABIO",
        "GABRIEL",
        "MICHEL",
        "ROBIN",
        "SIDNEY",
    }
)
# Nomes masculinos comuns terminados em A (evita classificar como F).
_PRIMEIRO_NOME_MASC_TERMINA_A = frozenset({"JOSUA", "JOSHUA", "LUCA", "NICOLA"})


def inferir_sexo_por_nome(nome: Optional[str]) -> Optional[str]:
    """
    Infere M/F pelo primeiro nome (heurística PT-BR).
    Retorna None se incerto — não inventa sexo.
    """
    bruto = " ".join(str(nome or "").split())
    if not bruto:
        return None
    primeiro = bruto.split()[0]
    chave = _sem_acento_upper(primeiro)
    if len(chave) < _PRIMEIRO_NOME_MIN:
        return None
    if chave in _PRIMEIRO_NOME_AMBIGUO:
        return None
    if chave in _PRIMEIRO_NOME_FEMININO:
        return "F"
    if chave in _PRIMEIRO_NOME_MASCULINO:
        return "M"
    if chave in _PRIMEIRO_NOME_MASC_TERMINA_A:
        return "M"
    if chave.endswith("OS") and len(chave) >= _PRIMEIRO_NOME_MIN:
        return "M"
    if chave.endswith("O") and len(chave) >= _PRIMEIRO_NOME_MIN:
        return "M"
    if chave.endswith("A") and len(chave) >= _PRIMEIRO_NOME_MIN:
        return "F"
    return None


def nascimento_ddmmaaaa(value: Optional[str]) -> Optional[str]:
    """Converte data da origem para DDMMAAAA (máscara APAC sem barras)."""
    if not value:
        return None
    s = str(value).strip()
    for sep in ("/", "-", "."):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) == 3:
                a, b, c = parts
                # DD/MM/YYYY ou YYYY/MM/DD
                if len(a) == 4 and len(c) <= 2:
                    y, m, d = a, b.zfill(2), c.zfill(2)
                else:
                    d, m, y = a.zfill(2), b.zfill(2), c
                    if len(y) == 2:
                        y = ("20" if int(y) < 50 else "19") + y
                if len(y) == 4 and len(d) == 2 and len(m) == 2:
                    return f"{d}{m}{y}"
            break
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) != 8:
        return None
    # Preferir DDMMAAAA (origem BR); senão AAAAMMDD → DDMMAAAA.
    d, m, y = int(digits[0:2]), int(digits[2:4]), int(digits[4:8])
    if ymd_valido(y, m, d):
        return digits
    y2, m2, d2 = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
    if ymd_valido(y2, m2, d2):
        return f"{digits[6:8]}{digits[4:6]}{digits[0:4]}"
    return None


def _mes_numero_por_nome(nome: str) -> Optional[int]:
    chave = _sem_acento(nome.casefold().strip())
    if not chave:
        return None
    if chave in _MESES_NOME:
        return _MESES_NOME[chave]
    for token, num in _MESES_NOME.items():
        if len(token) >= 3 and (chave == token or chave.startswith(token)):
            return num
    return None


def _nascimento_texto_mes_extenso(texto: str) -> Optional[str]:
    s = str(texto).strip()
    if not s:
        return None
    m = _RE_MES_DIA_ANO.match(s)
    if m:
        mes = _mes_numero_por_nome(m.group(1))
        dia = int(m.group(2))
        ano = int(m.group(3))
        if mes and ymd_valido(ano, mes, dia):
            return f"{dia:02d}{mes:02d}{ano:04d}"
    m = _RE_DIA_DE_MES.match(s)
    if m:
        dia = int(m.group(1))
        mes = _mes_numero_por_nome(m.group(2))
        ano = int(m.group(3))
        if mes and ymd_valido(ano, mes, dia):
            return f"{dia:02d}{mes:02d}{ano:04d}"
    return None


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def normalizar_nascimento_origem(valor: Any) -> Optional[str]:
    """
    Converte nascimento de planilha (texto PT/EN, datetime Excel) para DDMMAAAA.
    Usado na borda ICARE; não altera leitura BIODATA.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        if not ymd_valido(valor.year, valor.month, valor.day):
            return None
        return f"{valor.day:02d}{valor.month:02d}{valor.year:04d}"
    texto = cell_as_text(valor)
    if not texto:
        return None
    dd = nascimento_ddmmaaaa(texto)
    if dd:
        return dd
    iso = texto.split()[0] if " " in texto and "-" in texto else texto
    dd = nascimento_ddmmaaaa(iso)
    if dd:
        return dd
    return _nascimento_texto_mes_extenso(texto)


def _sem_acento_upper(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").strip())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.upper()


def tipo_logradouro_do_endereco(endereco: Optional[str]) -> Optional[str]:
    """
    Detecta tipo de logradouro no texto do Endereco BIODATA.
    Casa a frase mais longa da lista F1 (VIA LOCAL antes de VIA).
    Ex.: 'VIA LOCAL 305' -> 'VIA LOCAL'; 'SEGUNDA TRAVESSA X' -> 'TRAVESSA'.
    """
    if not (endereco or "").strip():
        return None
    norm = _sem_acento_upper(endereco).replace("-", " ")
    norm = " ".join(norm.split())
    for tipo in tipos_logradouro_por_tamanho():
        tipo_norm = _sem_acento_upper(tipo).replace("-", " ")
        tipo_norm = " ".join(tipo_norm.split())
        if not tipo_norm:
            continue
        padrao = rf"(?<![A-Z0-9]){re.escape(tipo_norm)}(?![A-Z0-9])"
        if re.search(padrao, norm):
            return tipo
    # Atalhos comuns fora da lista F1
    tokens = set(re.findall(r"[A-Z0-9]+", norm))
    if "TV" in tokens:
        return "TRAVESSA"
    if "AV" in tokens:
        return "AVENIDA"
    return None


# Limite do campo NOME / NOME DA MAE no APAC Magnético (medido: 31º char vaza).
APAC_MAX_NOME = 30


def abreviar_nome_apac(nome: str, max_len: int = APAC_MAX_NOME) -> str:
    """
    Encaixa o nome no limite do Magnético abreviando do ultimo sobrenome para tras.
    Ex.: CLAUDIA MARQUILENE SILVA CUTRIM (31) -> CLAUDIA MARQUILENE SILVA C (26).
    Se ainda passar (1º nome sozinho > max_len), corta em max_len.
    """
    t = " ".join((nome or "").split())
    if not t:
        return ""
    t = _sem_acento_upper(t)
    if max_len <= 0:
        return ""
    if len(t) <= max_len:
        return t

    partes = t.split(" ")
    # Abrevia do ultimo token para o primeiro (exceto o 1º nome)
    while len(" ".join(partes)) > max_len:
        encurtou = False
        for i in range(len(partes) - 1, 0, -1):
            if len(partes[i]) > 1:
                partes[i] = partes[i][0]
                encurtou = True
                break
        if not encurtou:
            break

    resultado = " ".join(partes)
    if len(resultado) > max_len:
        return resultado[:max_len]
    return resultado
