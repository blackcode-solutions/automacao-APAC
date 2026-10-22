"""Checkpoint / retomada do gerar-set após erro fatal (um único SET)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apac_bot.config import AppConfig
from apac_bot.connectors.biodata_api import BiodataApiError
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.set_pipeline import (
    caminho_checkpoint,
    caminho_staging,
    carregar_checkpoint,
    cmd_gerar_set,
    limpar_checkpoint,
    record_from_dict,
    record_to_dict,
    salvar_checkpoint,
)


def _cfg(tmp_path: Path, *, limite: int = 0) -> AppConfig:
    raw = {
        "clinica_id": "oftalmocentro91",
        "sistema_origem": "mock",
        "planilha": {
            "caminho": str(tmp_path / "x.xlsx"),
            "aba": "A",
            "linha_cabecalho": 1,
            "colunas": {
                "PACIENTE": "PACIENTE",
                "COD": "COD.",
                "AUDITOR": "AUDITOR",
                "NUMERACAO": "NUMERAÇÃO",
            },
        },
        "dados_fixos": {
            "cnes_solicitante": "6618839",
            "cnes_executante": "6618839",
            "tipo_apac": "3",
            "codigo_procedimento": "0405050372",
            "cbo": "225265",
            "quantidade_procedimento": "1",
            "cns_executante": "701003891196892",
            "medico_solicitante_cns": "705609469670213",
            "medico_solicitante_nome": "ORCELIO REZENDE",
            "autorizador_cns": "708107527671032",
            "autorizador_nome": "MARQUES HENRIQUE MARTINS FEITO",
            "motivo_saida": "12",
            "carater_atend": "01",
            "cod_orgao_emiss": "M211130001",
            "cid_principal": "H250",
            "codigo_servico": "131",
            "codigo_classificacao": "003",
            "uf_ibge": "21",
            "nacionalidade": "010",
            "raca": "03",
            "codigo_logradouro": "008",
            "municipio_ibge_padrao": "211230",
            "nome_responsavel_padrao": "O MESMO",
            "tipo_atendimento": "00",
        },
        "export_set": {
            "limite_pacientes": limite,
            "pasta_saida": str(tmp_path / "export_set"),
            "competencia_padrao": "202609",
            "orgao_origem": "CLINICA DE SERVICOS MEDICOS GE",
            "sigla": "CSMG",
            "cgc": "01192155000210",
            "orgao_destino": "SECRETARIA DE SAUDE",
            "versao": "Versao 04.01",
        },
        "apac": {"paciente_inicio": "PAC 0"},
        "progresso": {"caminho_db": str(tmp_path / "progress.db")},
        "biodata": {"url": "https://exemplo.local"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return AppConfig(raw=raw, path=path)


def _lanc(i: int) -> Lancamento:
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original=f"21262054092{i}-{i}",
        numeracao_apac=f"21262054092{i}/{i}",
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome=f"PAC {i}",
        prontuario=str(1000 + i),
    )


def _pac_ok(pront: str) -> PacienteDados:
    idx = int(pront) - 1000
    return PacienteDados(
        nome=f"PAC {idx}",
        nome_mae=f"MAE DO PAC {idx}",
        cpf="03345250390",
        nascimento="27/10/1981",
        sexo="M",
        logradouro="JOACY PINHEIRO",
        numero="124",
        cep="65763000",
        bairro="CENTRO",
    )


def _connector_ok() -> MagicMock:
    connector = MagicMock()
    connector.buscar_por_prontuario = MagicMock(side_effect=_pac_ok)
    connector.close = MagicMock()
    return connector


def test_record_roundtrip_dict(tmp_path: Path):
    cfg = _cfg(tmp_path)
    fila = [_lanc(0)]
    connector = _connector_ok()
    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector
    ):
        assert cmd_gerar_set(cfg) == 0

    loaded = carregar_checkpoint(cfg)
    assert loaded is None  # sucesso limpa checkpoint

    # Roundtrip via salvar/carregar forçado
    from apac_bot.set_pipeline import montar_record_paciente

    lanc = fila[0]
    lanc.paciente = _pac_ok(lanc.prontuario or "1000")
    rec = montar_record_paciente(cfg, lanc, competencia="202609")
    salvar_checkpoint(cfg, competencia="202609", records=[rec])
    loaded = carregar_checkpoint(cfg)
    assert loaded is not None
    comp, records = loaded
    assert comp == "202609"
    assert len(records) == 1
    assert record_to_dict(records[0]) == record_to_dict(record_from_dict(record_to_dict(rec)))
    limpar_checkpoint(cfg)


def test_abort_salva_checkpoint_e_set_parcial(tmp_path: Path):
    cfg = _cfg(tmp_path)
    fila = [_lanc(i) for i in range(4)]
    calls = {"n": 0}

    def buscar(pront: str):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise BiodataApiError("Falha de rede simulada")
        return _pac_ok(pront)

    connector = MagicMock()
    connector.buscar_por_prontuario = MagicMock(side_effect=buscar)
    connector.close = MagicMock()

    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector
    ):
        code = cmd_gerar_set(cfg)

    assert code == 2
    assert caminho_checkpoint(cfg).is_file()
    staging = caminho_staging(cfg)
    assert staging.is_file()
    text = staging.read_bytes().decode("latin-1")
    assert "000002" in text[:30]
    assert text.count("\r\n14") == 2
    loaded = carregar_checkpoint(cfg)
    assert loaded is not None
    assert len(loaded[1]) == 2


def test_retoma_completa_mesmo_set_unico(tmp_path: Path):
    cfg = _cfg(tmp_path)
    fila = [_lanc(i) for i in range(4)]
    calls = {"n": 0}

    def buscar_primeira(pront: str):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise BiodataApiError("Falha de rede simulada")
        return _pac_ok(pront)

    connector1 = MagicMock()
    connector1.buscar_por_prontuario = MagicMock(side_effect=buscar_primeira)
    connector1.close = MagicMock()

    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector1
    ):
        assert cmd_gerar_set(cfg) == 2

    staging_path = caminho_staging(cfg)
    assert staging_path.is_file()

    connector2 = _connector_ok()
    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector2
    ):
        code = cmd_gerar_set(cfg)

    assert code == 0
    assert not caminho_checkpoint(cfg).is_file()
    text = staging_path.read_bytes().decode("latin-1")
    assert "000004" in text[:30]
    assert text.count("\r\n14") == 4
    # Só os pendentes (2) foram buscados de novo
    assert connector2.buscar_por_prontuario.call_count == 2


def test_sem_checkpoint_nao_filtra_por_progresso(tmp_path: Path):
    cfg = _cfg(tmp_path)
    fila = [_lanc(i) for i in range(3)]
    connector = _connector_ok()

    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector
    ), patch(
        "apac_bot.set_pipeline.filtrar_pendentes_lote"
    ) as filtrar:
        code = cmd_gerar_set(cfg)

    assert code == 0
    filtrar.assert_not_called()
    assert connector.buscar_por_prontuario.call_count == 3


def test_staging_atualizado_apos_primeiro_paciente(tmp_path: Path):
    """Preview ao vivo: após 1 OK o lote_atual.SET já existe com 1 APAC."""
    cfg = _cfg(tmp_path)
    fila = [_lanc(i) for i in range(3)]
    calls = {"n": 0}
    staging = caminho_staging(cfg)

    def buscar(pront: str):
        calls["n"] += 1
        if calls["n"] >= 2:
            # 1º paciente já foi gravado no staging antes desta busca.
            assert staging.is_file(), "staging deveria existir após 1º OK"
            text = staging.read_bytes().decode("latin-1")
            assert "000001" in text[:30]
            assert text.count("\r\n14") == 1
            raise BiodataApiError("parar no 2º para inspecionar parcial")
        return _pac_ok(pront)

    connector = MagicMock()
    connector.buscar_por_prontuario = MagicMock(side_effect=buscar)
    connector.close = MagicMock()

    with patch(
        "apac_bot.set_pipeline.listar_lancamentos_a_partir", return_value=fila
    ), patch(
        "apac_bot.set_pipeline.build_connector", return_value=connector
    ):
        code = cmd_gerar_set(cfg)

    assert code == 2
    assert staging.is_file()
    text = staging.read_bytes().decode("latin-1")
    assert "000001" in text[:30]
