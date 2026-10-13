from __future__ import annotations

from typing import Any, Optional


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


def cpf_digitos(value: Optional[str]) -> str:
    """Retorna só dígitos do CPF (vazio se inválido/ausente)."""
    if not value:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def tem_cpf_valido(value: Optional[str]) -> bool:
    """True se houver 11 dígitos após limpar máscara."""
    return len(cpf_digitos(value)) == 11


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
    # YYYYMMDD vs DDMMAAAA
    if digits[:2] in {"19", "20"}:
        return digits[6:8] + digits[4:6] + digits[0:4]
    return digits
