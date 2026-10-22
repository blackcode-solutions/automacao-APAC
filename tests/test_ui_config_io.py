"""Testes do merge/save da UI (sem abrir janela gráfica)."""

import json
from pathlib import Path

import pytest

from apac_bot.ui.config_io import (
    CNES_POR_CLINICA,
    DADOS_FIXOS_GLAUCOMA_OCULTOS,
    DADOS_FIXOS_PADRAO_OCULTOS,
    DADOS_FIXOS_UI_KEYS,
    MODALIDADE_GLAUCOMA,
    MODALIDADE_PADRAO,
    UI_SECOES_GLAUCOMA,
    UI_SECOES_TELA,
    ConfigIoError,
    UiFormData,
    aplicar_defaults_clinica,
    codigo_orgao_emiss,
    form_from_raw,
    merge_form_into_raw,
    modalidade_ui_label,
    normalizar_modalidade,
    save_form,
    save_modalidade,
    secoes_para_modalidade,
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
        "planilha_prontuarios": {
            "caminho": "data/prontuarios.xlsx",
            "aba": "APAC ",
            "linha_cabecalho": 3,
            "colunas": {
                "PRONTUARIO": "Prontuário",
                "CLIENTE": "Cliente",
            },
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
        planilha_prontuarios_caminho="data/prontuarios.xlsx",
        paciente_inicio="PACIENTE A",
        dados_fixos=dados,
    )
    for k, v in overrides.items():
        if k in (
            "sistema_origem",
            "clinica_id",
            "planilha_caminho",
            "planilha_prontuarios_caminho",
            "planilha_aba_glaucoma",
            "paciente_inicio",
            "modalidade",
        ):
            setattr(form, k, v)
        else:
            form.dados_fixos[k] = v
    return form


def test_ui_secoes_tela_flatten():
    flatten = tuple(key for _titulo, keys in UI_SECOES_TELA for key in keys)
    assert DADOS_FIXOS_UI_KEYS == (
        flatten
        + tuple(DADOS_FIXOS_PADRAO_OCULTOS.keys())
        + (
            "autorizador_cns",
            "autorizador_nome",
        )
    )
    assert len(DADOS_FIXOS_UI_KEYS) == len(set(DADOS_FIXOS_UI_KEYS))
    assert "cod_orgao_emiss" not in flatten
    assert "cod_orgao_emiss" in DADOS_FIXOS_PADRAO_OCULTOS
    assert "cod_orgao_emiss" in DADOS_FIXOS_GLAUCOMA_OCULTOS
    assert "autorizador_cns" not in flatten
    assert "tipo_apac" not in flatten
    assert "quantidade_procedimento" not in flatten
    assert "motivo_saida" not in flatten
    assert "carater_atend" not in flatten
    assert "tipo_apac" in DADOS_FIXOS_UI_KEYS
    assert "quantidade_procedimento" in DADOS_FIXOS_UI_KEYS
    assert "cod_orgao_emiss" in DADOS_FIXOS_UI_KEYS


def test_merge_forca_campos_fixos_ocultos_padrao():
    form = _form_ok(
        tipo_apac="1",
        quantidade_procedimento="99",
        motivo_saida="00",
        carater_atend="99",
    )
    # Simula form sem os campos ocultos (como a UI após remoção).
    for key in DADOS_FIXOS_PADRAO_OCULTOS:
        form.dados_fixos.pop(key, None)
    merged = merge_form_into_raw(_base_raw(), form)
    assert merged["dados_fixos"]["tipo_apac"] == "3"
    assert merged["dados_fixos"]["quantidade_procedimento"] == "1"
    assert merged["dados_fixos"]["motivo_saida"] == "12"
    assert merged["dados_fixos"]["carater_atend"] == "01"
    assert merged["dados_fixos"]["cod_orgao_emiss"] == "M211130001"
    # Mesmo com valores errados no form, o merge sobrescreve.
    form2 = _form_ok(
        tipo_apac="1",
        quantidade_procedimento="99",
        motivo_saida="00",
        carater_atend="99",
        cod_orgao_emiss="E210000001",
    )
    merged2 = merge_form_into_raw(_base_raw(), form2)
    assert merged2["dados_fixos"]["tipo_apac"] == "3"
    assert merged2["dados_fixos"]["quantidade_procedimento"] == "1"
    assert merged2["dados_fixos"]["motivo_saida"] == "12"
    assert merged2["dados_fixos"]["carater_atend"] == "01"
    assert merged2["dados_fixos"]["cod_orgao_emiss"] == "M211130001"


def test_merge_forca_cod_orgao_emiss_por_modalidade():
    form_padrao = _form_ok(
        modalidade=MODALIDADE_PADRAO, cod_orgao_emiss="E210000001"
    )
    merged_p = merge_form_into_raw(_base_raw(), form_padrao)
    assert merged_p["dados_fixos"]["cod_orgao_emiss"] == "M211130001"

    form_glau = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA, cod_orgao_emiss="M211130001"
    )
    merged_g = merge_form_into_raw(_base_raw(), form_glau)
    assert merged_g["dados_fixos"]["cod_orgao_emiss"] == "E210000001"


def test_merge_forca_cid_principal_por_modalidade():
    form_padrao = _form_ok(
        modalidade=MODALIDADE_PADRAO, cid_principal="H401"
    )
    merged_p = merge_form_into_raw(_base_raw(), form_padrao)
    assert merged_p["dados_fixos"]["cid_principal"] == "H250"

    form_glau = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA, cid_principal="H250"
    )
    merged_g = merge_form_into_raw(_base_raw(), form_glau)
    assert merged_g["dados_fixos"]["cid_principal"] == "H401"


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
    assert form.planilha_prontuarios_caminho == "data/prontuarios.xlsx"
    assert form.paciente_inicio == "FULANO"
    assert form.modalidade == MODALIDADE_PADRAO
    assert form.dados_fixos["cnes_solicitante"] == "111"


def test_modalidade_default_quando_ausente():
    assert normalizar_modalidade("") == MODALIDADE_PADRAO
    assert normalizar_modalidade("APAC Glaucoma") == MODALIDADE_GLAUCOMA
    assert modalidade_ui_label("padrao") == "APAC Padrão"
    assert secoes_para_modalidade(MODALIDADE_PADRAO) is UI_SECOES_TELA
    assert secoes_para_modalidade(MODALIDADE_GLAUCOMA) is UI_SECOES_GLAUCOMA
    form = form_from_raw(_base_raw())
    assert form.modalidade == MODALIDADE_PADRAO


def test_secoes_glaucoma_tres_cards_sem_tipo_apac():
    secoes = secoes_para_modalidade(MODALIDADE_GLAUCOMA)
    assert secoes == (
        ("Identificação", ("cnes_solicitante", "cnes_executante")),
        ("Procedimentos", ("cbo", "cns_executante")),
        (
            "Solicitação / Autorização",
            ("medico_solicitante_cns", "medico_solicitante_nome"),
        ),
    )
    flatten = tuple(key for _titulo, keys in secoes for key in keys)
    assert "tipo_apac" not in flatten
    assert "quantidade_procedimento" not in flatten
    assert "motivo_saida" not in flatten
    assert "carater_atend" not in flatten
    assert DADOS_FIXOS_GLAUCOMA_OCULTOS == {
        "tipo_apac": "1",
        "tipo_atendimento": "07",
        "motivo_saida": "15",
        "cod_orgao_emiss": "E210000001",
        "cid_principal": "H401",
    }


def test_glaucoma_forca_tipo_apac_1_e_ocultos_padrao():
    form = _form_ok(modalidade=MODALIDADE_GLAUCOMA, tipo_apac="3")
    completos = form.dados_fixos_completos()
    assert completos["tipo_apac"] == "1"
    assert completos["tipo_atendimento"] == "07"
    assert completos["quantidade_procedimento"] == "1"
    assert completos["motivo_saida"] == "15"
    assert completos["carater_atend"] == "01"
    merged = merge_form_into_raw(_base_raw(), form)
    assert merged["dados_fixos"]["tipo_apac"] == "1"
    assert merged["dados_fixos"]["tipo_atendimento"] == "07"
    assert merged["dados_fixos"]["motivo_saida"] == "15"
    assert merged["dados_fixos"]["quantidade_procedimento"] == "1"
    assert merged["apac"]["modalidade"] == MODALIDADE_GLAUCOMA


def test_modalidade_roundtrip_merge():
    raw = _base_raw()
    form = _form_ok(modalidade=MODALIDADE_GLAUCOMA)
    merged = merge_form_into_raw(raw, form)
    assert merged["apac"]["modalidade"] == MODALIDADE_GLAUCOMA
    assert merged["apac"]["titulo_janela"] == "APAC MAGNETICO"
    loaded = form_from_raw(merged)
    assert loaded.modalidade == MODALIDADE_GLAUCOMA


def test_validate_glaucoma_aceita_form_ok():
    form = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_caminho="data/cenario.xlsx",
        planilha_prontuarios_caminho="",
        planilha_aba_glaucoma="TRAT 0303050187",
    )
    erros = validate_form(form)
    assert erros == []
    assert "ainda não configurada" not in " ".join(erros).lower()


def test_validate_glaucoma_aceita_sem_aba():
    form = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_caminho="data/cenario.xlsx",
        planilha_prontuarios_caminho="",
        planilha_aba_glaucoma="",
    )
    erros = validate_form(form)
    assert erros == []


def test_form_from_raw_migra_planilha_glaucoma_legado_para_planilha():
    raw = _base_raw()
    raw["apac"]["modalidade"] = MODALIDADE_GLAUCOMA
    raw["planilha"]["caminho"] = ""
    raw["planilha"]["aba_glaucoma"] = "Base Consultas"
    raw["planilha_glaucoma"] = {"caminho": "data/cenario_legado.xlsx"}
    form = form_from_raw(raw)
    assert form.planilha_caminho == "data/cenario_legado.xlsx"
    assert form.planilha_aba_glaucoma == "Base Consultas"


def test_merge_glaucoma_preserva_prontuarios_e_remove_bloco_glaucoma():
    raw = _base_raw()
    raw["planilha_glaucoma"] = {"caminho": "data/old.xlsx"}
    assert raw["planilha_prontuarios"]["caminho"] == "data/prontuarios.xlsx"
    form = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_prontuarios_caminho="",
        planilha_caminho="data/cenario.xlsx",
        planilha_aba_glaucoma="TRAT 0303050187",
    )
    merged = merge_form_into_raw(raw, form)
    assert merged["apac"]["modalidade"] == MODALIDADE_GLAUCOMA
    assert merged["planilha_prontuarios"]["caminho"] == "data/prontuarios.xlsx"
    assert merged["planilha"]["caminho"] == "data/cenario.xlsx"
    assert merged["planilha"]["aba_glaucoma"] == "TRAT 0303050187"
    assert merged["planilha"]["aba"] == "Lançamentos"
    assert "planilha_glaucoma" not in merged


def test_save_modalidade_sem_validar_form(tmp_path: Path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(_base_raw()), encoding="utf-8")
    assert save_modalidade(cfg, "APAC Glaucoma") == MODALIDADE_GLAUCOMA
    loaded = json.loads(cfg.read_text(encoding="utf-8"))
    assert loaded["apac"]["modalidade"] == MODALIDADE_GLAUCOMA
    assert loaded["apac"]["paciente_inicio"] == "FULANO"


def test_merge_preserva_chaves_alheias():
    raw = _base_raw()
    form = _form_ok()
    merged = merge_form_into_raw(raw, form)
    assert merged["biodata"]["url"] == "https://exemplo.local"
    assert merged["biodata"]["locators"] == {"x": 1}
    assert merged["timeouts"]["biodata_ms"] == 1000
    assert merged["apac"]["titulo_janela"] == "APAC MAGNETICO"
    assert merged["apac"]["paciente_inicio"] == "PACIENTE A"
    assert merged["apac"]["modalidade"] == MODALIDADE_PADRAO
    assert merged["dados_fixos"]["extra_nao_ui"] == "manter"
    assert merged["dados_fixos"]["cnes_solicitante"] == "6618839"
    assert merged["sistema_origem"] == "biodata"
    assert merged["clinica_id"] == "oftalmocentro91"
    assert merged["planilha"]["caminho"] == "data/planilha.xlsx"
    assert merged["planilha"]["aba"] == "Lançamentos"
    assert merged["planilha_prontuarios"]["caminho"] == "data/prontuarios.xlsx"
    assert merged["planilha_prontuarios"]["aba"] == "APAC "


def test_merge_cria_defaults_planilha_prontuarios():
    raw = _base_raw()
    del raw["planilha_prontuarios"]
    form = _form_ok(planilha_prontuarios_caminho="data/nova_pront.xlsx")
    merged = merge_form_into_raw(raw, form)
    assert merged["planilha_prontuarios"]["caminho"] == "data/nova_pront.xlsx"
    assert merged["planilha_prontuarios"]["aba"] == "APAC "
    assert merged["planilha_prontuarios"]["linha_cabecalho"] == 3
    assert merged["planilha_prontuarios"]["colunas"]["PRONTUARIO"] == "Prontuário"


def test_merge_normaliza_cns_so_digitos():
    form = _form_ok(medico_solicitante_cns="705.609.469.670.213")
    merged = merge_form_into_raw(_base_raw(), form)
    assert merged["dados_fixos"]["medico_solicitante_cns"] == "705609469670213"


def test_validate_planilha_prontuarios_obrigatoria():
    form = _form_ok(planilha_prontuarios_caminho="")
    erros = validate_form(form)
    assert any("prontuários" in e.lower() for e in erros)


def test_validate_glaucoma_aceita_sem_planilha_prontuarios():
    form = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_prontuarios_caminho="",
        planilha_caminho="data/cenario.xlsx",
        planilha_aba_glaucoma="Base Consultas",
    )
    assert validate_form(form) == []


def test_merge_glaucoma_permite_prontuarios_vazio():
    """Glaucoma não grava prontuários vazios por cima do path do Padrão."""
    form = _form_ok(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_prontuarios_caminho="",
        planilha_caminho="data/cenario.xlsx",
        planilha_aba_glaucoma="Base Consultas",
    )
    merged = merge_form_into_raw(_base_raw(), form)
    assert merged["apac"]["modalidade"] == MODALIDADE_GLAUCOMA
    assert merged["planilha_prontuarios"]["caminho"] == "data/prontuarios.xlsx"
    assert merged["planilha_prontuarios"]["aba"] == "APAC "
    assert merged["planilha"]["aba_glaucoma"] == "Base Consultas"


def test_padrao_forca_tipo_apac_3_mesmo_com_valor_errado():
    form = _form_ok(tipo_apac="9")
    assert form.dados_fixos_completos()["tipo_apac"] == "3"
    assert validate_form(form) == []


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
    assert loaded["dados_fixos"]["tipo_apac"] == "3"
    assert loaded["biodata"]["locators"] == {"x": 1}
    assert loaded["dados_fixos"]["extra_nao_ui"] == "manter"
    assert loaded["planilha_prontuarios"]["caminho"] == "data/prontuarios.xlsx"


def test_save_form_bloqueia_invalido(tmp_path: Path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(_base_raw()), encoding="utf-8")
    form = _form_ok(cnes_solicitante="")
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
