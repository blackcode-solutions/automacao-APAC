"""Testes do merge/save da UI (sem abrir janela gráfica)."""

import json
from pathlib import Path

import pytest

from apac_bot.ui.config_io import (
    CNES_POR_CLINICA,
    DADOS_FIXOS_UI_KEYS,
    UI_SECOES_TELA,
    ConfigIoError,
    UiFormData,
    aplicar_defaults_clinica,
    codigo_orgao_emiss,
    form_from_raw,
    merge_form_into_raw,
    save_form,
    tipo_orgao_emiss,
    validate_form,
)


def _base_raw() -> dict:
    return {
        "clinica_id": "clinica_exemplo",
        "sistema_origem": "mock",
        "biodata": {"url": "https://exemplo.local", "locators": {"x": 1}},
        "planilha": {
            "caminho": "data/planilha_exemplo.xlsx",
            "aba": "Lançamentos",
            "colunas": {"PACIENTE": "PACIENTE"},
        },
        "apac": {
            "titulo_janela": "APAC MAGNETICO",
            "paciente_inicio": "FULANO",
            "passos": [],
        },
        "dados_fixos": {
            "cnes_solicitante": "111",
            "cnes_executante": "222",
            "tipo_apac": "3",
            "cbo": "225265",
            "extra_nao_ui": "manter",
        },
        "timeouts": {"biodata_ms": 1000},
    }


def _form_ok(**overrides) -> UiFormData:
    dados = {
        "cnes_solicitante": "6618839",
        "cnes_executante": "6618839",
        "tipo_apac": "3",
        "codigo_procedimento": "0405050372",
        "cbo": "225265",
        "quantidade_procedimento": "1",
        "cns_executante": "701003891196892",
        "motivo_saida": "12",
        "carater_atend": "01",
        "medico_solicitante_cns": "705609469670213",
        "medico_solicitante_nome": "0RCELIO REZENDE",
        "autorizador_cns": "708107527671032",
        "autorizador_nome": "MARQUES HENRIQUE MARTINS FEITO",
        "cod_orgao_emiss": "M211130001",
    }
    form = UiFormData(
        sistema_origem="biodata",
        clinica_id="oftalmocentro91",
        planilha_caminho="data/planilha.xlsx",
        paciente_inicio="PACIENTE A",
        dados_fixos=dados,
    )
    for k, v in overrides.items():
        if k in (
            "sistema_origem",
            "clinica_id",
            "planilha_caminho",
            "paciente_inicio",
        ):
            setattr(form, k, v)
        else:
            form.dados_fixos[k] = v
    return form


def test_ui_secoes_tela_flatten():
    flatten = tuple(key for _titulo, keys in UI_SECOES_TELA for key in keys)
    assert DADOS_FIXOS_UI_KEYS == flatten + (
        "autorizador_cns",
        "autorizador_nome",
        "cod_orgao_emiss",
    )
    assert len(DADOS_FIXOS_UI_KEYS) == len(set(DADOS_FIXOS_UI_KEYS))
    assert "cod_orgao_emiss" not in flatten
    assert "autorizador_cns" not in flatten


def test_orgao_emiss_municipal_estadual():
    assert codigo_orgao_emiss("Municipal") == "M211130001"
    assert codigo_orgao_emiss("Estadual") == "E210000001"
    assert tipo_orgao_emiss("M211130001") == "Municipal"
    assert tipo_orgao_emiss("E210000001") == "Estadual"
    assert tipo_orgao_emiss("desconhecido") == "Municipal"


def test_cnes_por_clinica_oftalmocentro91():
    assert CNES_POR_CLINICA["oftalmocentro91"] == {
        "cnes_solicitante": "6618839",
        "cnes_executante": "6618839",
    }
    assert aplicar_defaults_clinica("oftalmocentro91") == {
        "cnes_solicitante": "6618839",
        "cnes_executante": "6618839",
    }
    assert aplicar_defaults_clinica("desconhecida") == {}


def test_form_from_raw():
    form = form_from_raw(_base_raw())
    # mock → biodata; clínica travada para oftalmocentro91
    assert form.sistema_origem == "biodata"
    assert form.clinica_id == "oftalmocentro91"
    assert form.planilha_caminho == "data/planilha_exemplo.xlsx"
    assert form.paciente_inicio == "FULANO"
    assert form.dados_fixos["cnes_solicitante"] == "111"


def test_merge_preserva_chaves_alheias():
    raw = _base_raw()
    form = _form_ok()
    merged = merge_form_into_raw(raw, form)
    assert merged["biodata"]["url"] == "https://exemplo.local"
    assert merged["biodata"]["locators"] == {"x": 1}
    assert merged["timeouts"]["biodata_ms"] == 1000
    assert merged["apac"]["titulo_janela"] == "APAC MAGNETICO"
    assert merged["apac"]["paciente_inicio"] == "PACIENTE A"
    assert merged["dados_fixos"]["extra_nao_ui"] == "manter"
    assert merged["dados_fixos"]["cnes_solicitante"] == "6618839"
    assert merged["sistema_origem"] == "biodata"
    assert merged["clinica_id"] == "oftalmocentro91"
    assert merged["planilha"]["caminho"] == "data/planilha.xlsx"
    assert merged["planilha"]["aba"] == "Lançamentos"


def test_merge_normaliza_cns_so_digitos():
    form = _form_ok(medico_solicitante_cns="705.609.469.670.213")
    merged = merge_form_into_raw(_base_raw(), form)
    assert merged["dados_fixos"]["medico_solicitante_cns"] == "705609469670213"


def test_validate_tipo_apac():
    form = _form_ok(tipo_apac="9")
    erros = validate_form(form)
    assert any("Tipo APAC" in e for e in erros)


def test_validate_cns_tamanho():
    form = _form_ok(autorizador_cns="123")
    erros = validate_form(form)
    assert any("autorizador" in e.lower() and "15" in e for e in erros)


def test_save_form_roundtrip(tmp_path: Path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(_base_raw(), ensure_ascii=False, indent=2), encoding="utf-8")
    form = _form_ok()
    save_form(cfg, form)
    loaded = json.loads(cfg.read_text(encoding="utf-8"))
    assert loaded["sistema_origem"] == "biodata"
    assert loaded["clinica_id"] == "oftalmocentro91"
    assert loaded["dados_fixos"]["medico_solicitante_cns"] == "705609469670213"
    assert loaded["biodata"]["locators"] == {"x": 1}
    assert loaded["dados_fixos"]["extra_nao_ui"] == "manter"


def test_save_form_bloqueia_invalido(tmp_path: Path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(_base_raw()), encoding="utf-8")
    form = _form_ok(tipo_apac="x")
    with pytest.raises(ConfigIoError):
        save_form(cfg, form)


def test_validate_sistema_e_clinica_biodata():
    form = _form_ok(clinica_id="outra")
    erros = validate_form(form)
    assert any("clínica" in e.lower() for e in erros)


def test_validate_sisac_sem_clinica_cadastrada():
    form = _form_ok(sistema_origem="sisac", clinica_id="")
    erros = validate_form(form)
    assert any("Nenhuma clínica" in e or "clínica" in e.lower() for e in erros)
