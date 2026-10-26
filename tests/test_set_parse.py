"""Parse do SET/TXT a partir da fixture golden APOFTAL9."""

from __future__ import annotations

from pathlib import Path

import pytest

from apac_bot.set_layout import SetLayoutError
from apac_bot.set_parse import numeracoes_no_set, parse_set_bytes, parse_set_file

FIXTURE = Path(__file__).parent / "fixtures" / "APOFTAL9.txt"


def test_parse_fixture_apac_oftalmologia():
    parsed = parse_set_file(FIXTURE)
    assert parsed.competencia == "202609"
    assert parsed.orgao_origem == "CLINICA DE SERVICOS MEDICOS GE"
    assert len(parsed.pacientes) == 3

    primeiro = parsed.pacientes[0]
    assert primeiro.numeracao == "2126205409218"
    assert primeiro.nome == "CLERIVAN ANDRADE DE ARAUJO"
    assert primeiro.nascimento == "19811027"
    assert len(primeiro.procedimentos) == 1
    proc = primeiro.procedimentos[0]
    assert proc.codigo_procedimento == "0405050372"
    assert proc.cbo == "225265"
    assert proc.quantidade == "1"

    nums = numeracoes_no_set(parsed)
    assert "2126205409218" in nums
    assert "2126205409229" in nums
    assert "2126205409230" in nums


def test_parse_set_vazio_erro():
    with pytest.raises(SetLayoutError, match="vazio"):
        parse_set_bytes(b"")


def test_parse_cabecalho_invalido():
    with pytest.raises(SetLayoutError):
        parse_set_bytes(b"XX" + b" " * 132 + b"\r\n")
