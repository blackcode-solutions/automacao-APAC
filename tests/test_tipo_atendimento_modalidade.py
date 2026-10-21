"""tipo_atendimento (apa_tipate) conforme apac.modalidade."""

from __future__ import annotations

from pathlib import Path

from apac_bot.config import MODALIDADE_GLAUCOMA, MODALIDADE_PADRAO, AppConfig
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.set_pipeline import (
    montar_record_paciente,
    servico_classificacao_glaucoma,
)


def _cfg(modalidade: str) -> AppConfig:
    return AppConfig(
        raw={
            "clinica_id": "oftalmocentro91",
            "apac": {"modalidade": modalidade},
            "dados_fixos": {
                "cnes_solicitante": "6618839",
                "cnes_executante": "6618839",
                "tipo_apac": "3",
                "tipo_atendimento": "00",
                "codigo_procedimento": "0405050372",
                "cid_principal": "H250",
                "medico_solicitante_nome": "ORCELIO",
                "medico_solicitante_cns": "705609469670213",
                "autorizador_nome": "MARQUES",
                "autorizador_cns": "708107527671032",
                "cns_executante": "701003891196892",
                "cod_orgao_emiss": "M211130001",
                "cbo": "225265",
                "codigo_servico": "131",
                "codigo_classificacao": "003",
            },
        },
        path=Path("config.json"),
    )


def _lanc() -> Lancamento:
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original="2126205409218",
        numeracao_apac="2126205409218",
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome="PAC TESTE",
        prontuario="123",
        paciente=PacienteDados(
            nome="PAC TESTE",
            nome_mae="MAE TESTE",
            cpf="03345250390",
            nascimento="19811027",
            sexo="M",
            logradouro="RUA TESTE",
            numero="10",
            cep="65763000",
            bairro="CENTRO",
        ),
    )


def test_tipo_atendimento_padrao_usa_config_00():
    rec = montar_record_paciente(_cfg(MODALIDADE_PADRAO), _lanc(), competencia="202609")
    assert rec.corpo.tipo_atendimento == "00"
    assert rec.corpo.tipo_apac == "3"
    assert rec.corpo.motivo_saida == "12"
    assert rec.cid.cid_principal == "H250"
    assert rec.corpo.cid_causas == ""
    assert rec.corpo.prontuario == ""


def test_tipo_atendimento_glaucoma_forca_07():
    rec = montar_record_paciente(
        _cfg(MODALIDADE_GLAUCOMA), _lanc(), competencia="202609"
    )
    assert rec.corpo.tipo_atendimento == "07"
    assert rec.corpo.tipo_apac == "1"
    # 1 procedimento → 12 / H400
    assert rec.corpo.motivo_saida == "12"
    assert rec.cid.cid_principal == "H400"
    assert rec.corpo.cid_causas == ""
    assert rec.corpo.prontuario == ""


def test_glaucoma_data_obito_alta_mes_competencia_nao_fim_validade():
    """Magnético 010082: encerramento no mês da competência; validade +2."""
    rec = montar_record_paciente(
        _cfg(MODALIDADE_GLAUCOMA), _lanc(), competencia="202609"
    )
    assert rec.corpo.data_fim_val == "20261130"
    assert rec.corpo.data_obito_alta == "20260930"


def test_cid_principal_glaucoma_um_proc_ignora_json_h250():
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    assert cfg.raw["dados_fixos"]["cid_principal"] == "H250"
    rec = montar_record_paciente(cfg, _lanc(), competencia="202609")
    assert rec.cid.cid_principal == "H400"


def test_tipo_apac_glaucoma_ignora_json_3():
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    assert cfg.raw["dados_fixos"]["tipo_apac"] == "3"
    rec = montar_record_paciente(cfg, _lanc(), competencia="202609")
    assert rec.corpo.tipo_apac == "1"


def test_tipo_apac_padrao_ignora_json_1():
    cfg = _cfg(MODALIDADE_PADRAO)
    cfg.raw["dados_fixos"]["tipo_apac"] = "1"
    rec = montar_record_paciente(cfg, _lanc(), competencia="202609")
    assert rec.corpo.tipo_apac == "3"


def test_motivo_saida_cid_glaucoma_multi_proc_ignora_json():
    """2+ procedimentos → 15/H401 mesmo se JSON tiver 12/H250."""
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    cfg.raw["dados_fixos"]["motivo_saida"] = "12"
    cfg.raw["dados_fixos"]["cid_principal"] = "H250"
    lanc = _lanc()
    lanc.codigos_associados = ["0303050187"]
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    assert len(rec.procedimentos) >= 2
    assert rec.corpo.motivo_saida == "15"
    assert rec.cid.cid_principal == "H401"


def test_motivo_saida_padrao_ignora_json_15():
    cfg = _cfg(MODALIDADE_PADRAO)
    cfg.raw["dados_fixos"]["motivo_saida"] = "15"
    rec = montar_record_paciente(cfg, _lanc(), competencia="202609")
    assert rec.corpo.motivo_saida == "12"


def test_glaucoma_procedimentos_da_planilha_com_associados():
    """Glaucoma ignora dados_fixos.codigo_procedimento; N linhas 13."""
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    cfg.raw["dados_fixos"]["codigo_procedimento"] = "0405050372"
    lanc = _lanc()
    lanc.codigo_original = "0303050160"
    lanc.codigo_apac = "0303050160"
    lanc.codigos_associados = ["0303050187", "0303050195"]
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    # Ordem: 1º associado → Código → demais associados; corpo 14 = 1º associado.
    assert rec.corpo.codigo_procedimento == "0303050187"
    assert [p.codigo_procedimento for p in rec.procedimentos] == [
        "0303050187",
        "0303050160",
        "0303050195",
    ]
    assert rec.corpo.motivo_saida == "15"
    assert rec.cid.cid_principal == "H401"


def test_glaucoma_um_procedimento_motivo_12_cid_h400():
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    lanc = _lanc()
    lanc.codigo_apac = "0303050012"
    lanc.codigos_associados = []
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    assert len(rec.procedimentos) == 1
    assert rec.corpo.motivo_saida == "12"
    assert rec.cid.cid_principal == "H400"


def test_padrao_continua_usando_codigo_fixo():
    cfg = _cfg(MODALIDADE_PADRAO)
    lanc = _lanc()
    lanc.codigo_apac = "9999999999"
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    assert rec.corpo.codigo_procedimento == "0405050372"
    assert len(rec.procedimentos) == 1
    assert rec.procedimentos[0].codigo_procedimento == "0405050372"


def test_servico_classificacao_glaucoma_tabela():
    assert servico_classificacao_glaucoma("0303050012") == ("131", "002")
    assert servico_classificacao_glaucoma("0303050187") == ("", "")
    assert servico_classificacao_glaucoma("0301010102") == ("131", "001")
    assert servico_classificacao_glaucoma("0303050160") == ("", "")
    assert servico_classificacao_glaucoma("") == ("", "")


def test_glaucoma_servico_classificacao_por_procedimento():
    cfg = _cfg(MODALIDADE_GLAUCOMA)
    lanc = _lanc()
    lanc.codigo_apac = "0303050012"
    lanc.codigos_associados = ["0303050187", "0301010102", "0303050160"]
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    pares = [
        (p.codigo_procedimento, p.codigo_servico, p.codigo_classificacao)
        for p in rec.procedimentos
    ]
    assert pares == [
        ("0303050187", "", ""),
        ("0303050012", "131", "002"),
        ("0301010102", "131", "001"),
        ("0303050160", "", ""),
    ]


def test_padrao_servico_classificacao_fixos_config():
    cfg = _cfg(MODALIDADE_PADRAO)
    lanc = _lanc()
    lanc.codigo_apac = "0303050187"
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    assert rec.procedimentos[0].codigo_servico == "131"
    assert rec.procedimentos[0].codigo_classificacao == "003"
