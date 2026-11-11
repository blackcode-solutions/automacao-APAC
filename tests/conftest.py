"""Fixtures compartilhadas nos testes."""


def raw_com_eyecare(raw: dict) -> dict:
    """Normaliza alias icare → eyecare em fixtures de teste."""
    out = dict(raw)
    if str(out.get("sistema_origem", "")).strip().lower() == "icare":
        out["sistema_origem"] = "eyecare"
    return out
