"""Pré-check de dados obrigatórios antes do Insert no APAC."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apac_bot.apac import (
    ApacBlockedError,
    DadosIncompletosError,
    buscar_paciente_biodata,
    open_apac_session,
)
from apac_bot.config import AppConfig
from apac_bot.connectors.mock_biodata import MockBiodataConnector
from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.pipeline import validar_dados_obrigatorios_apac
from apac_bot.progress import ProgressStore, filtrar_pendentes_lote


def _paciente_ok(**overrides) -> PacienteDados:
    base = dict(
        id_paciente="BIO-1",
        cpf="529.982.247-25",
        nome="MARIA SILVA",
        nome_mae="ANA SILVA",
        nascimento="01/01/1980",
        sexo="F",
    )
    base.update(overrides)
    return PacienteDados(**base)


def _lanc(nome: str = "MARIA SILVA FICTICIA", num: str = "1-1") -> Lancamento:
    return Lancamento(
        clinica_id="c1",
        numeracao_original=num,
        numeracao_apac=num.replace("-", "/"),
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome=nome,
        id_paciente="BIO-1001",
    )


def test_validar_ok():
    assert validar_dados_obrigatorios_apac(_paciente_ok(), "MARIA SILVA") is None


def test_validar_ok_so_cns():
    p = _paciente_ok(cpf=None, cns="708107527671032")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") is None


def test_validar_ok_cpf_com_cns_tambem():
    p = _paciente_ok(cns="708107527671032")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") is None


def test_validar_paciente_none():
    motivo = validar_dados_obrigatorios_apac(None, "X")
    assert motivo is not None
    assert "cpf/cns" in motivo
    assert "nome_mae" in motivo
    assert "nascimento" in motivo
    assert "sexo" in motivo


def test_validar_falta_cpf_e_cns():
    p = _paciente_ok(cpf=None, cns=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: cpf/cns"


def test_validar_cns_incompleto_sem_cpf():
    p = _paciente_ok(cpf=None, cns="123")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: cpf/cns"


def test_validar_falta_mae():
    p = _paciente_ok(nome_mae=None)
    assert "nome_mae" in (validar_dados_obrigatorios_apac(p, "MARIA SILVA") or "")


def test_validar_mae_igual_paciente():
    p = _paciente_ok(nome_mae="MARIA SILVA")
    assert "nome_mae" in (validar_dados_obrigatorios_apac(p, "MARIA SILVA") or "")


def test_validar_falta_nascimento():
    p = _paciente_ok(nascimento=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: nascimento"


def test_validar_falta_sexo():
    p = _paciente_ok(sexo=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: sexo"


def test_validar_varios_faltando():
    p = _paciente_ok(cpf="", cns="", nascimento="", sexo="")
    motivo = validar_dados_obrigatorios_apac(p, "MARIA SILVA")
    assert motivo == "faltam: cpf/cns, nascimento, sexo"


def test_buscar_paciente_ok_com_mock():
    c = MockBiodataConnector()
    lanc = _lanc()
    cpf = buscar_paciente_biodata(c, lanc)
    assert len(cpf) == 11
    assert lanc.paciente is not None
    assert lanc.paciente.sexo == "F"


def test_buscar_paciente_sem_sexo_levanta_dados_incompletos():
    p = _paciente_ok(sexo=None, id_paciente="BIO-X", nome="SEM SEXO")
    c = MockBiodataConnector(pacientes=[p])
    lanc = _lanc("SEM SEXO")
    lanc.id_paciente = "BIO-X"
    with pytest.raises(DadosIncompletosError) as exc:
        buscar_paciente_biodata(c, lanc)
    assert "sexo" in exc.value.motivo


def test_buscar_paciente_ambiguo_levanta_dados_incompletos():
    c = MockBiodataConnector()
    lanc = _lanc("PACIENTE AMBIGUO")
    lanc.id_paciente = None
    with pytest.raises(DadosIncompletosError) as exc:
        buscar_paciente_biodata(c, lanc)
    assert "ambígua" in (exc.value.motivo or str(exc.value))


def test_aguardando_revisao_nao_e_pulado(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc()
    store.upsert(lanc, EstadoLancamento.AGUARDANDO_REVISAO, motivo="faltam: sexo")
    pular, motivo = store.deve_pular(lanc)
    assert pular is False
    assert motivo is None


def test_filtrar_pendentes_inclui_aguardando_revisao(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    a = _lanc("AAA", "111-1")
    b = _lanc("BBB", "222-2")
    store.upsert(a, EstadoLancamento.AGUARDANDO_REVISAO, motivo="faltam: cpf")
    store.upsert(b, EstadoLancamento.CONCLUIDO, motivo="ok")
    pendentes, pulados, _alterados = filtrar_pendentes_lote([a, b], store)
    assert [l.paciente_nome for l in pendentes] == ["AAA"]
    assert len(pulados) == 1
    assert pulados[0][0].paciente_nome == "BBB"


def test_lote_pula_dados_incompletos_e_continua(tmp_path: Path):
    """DadosIncompletosError → AGUARDANDO_REVISAO + próximo; ApacBlockedError ainda aborta."""
    cfg = AppConfig(
        path=tmp_path / "config.json",
        raw={
            "clinica_id": "c1",
            "sistema_origem": "mock",
            "apac": {"titulo_janela": "APAC MAGNETICO"},
            "progresso": {"caminho_db": str(tmp_path / "progress.db")},
            "planilha": {
                "caminho": str(tmp_path / "x.xlsx"),
                "aba": "L",
                "colunas": {
                    "PACIENTE": "PACIENTE",
                    "COD": "COD",
                    "AUDITOR": "AUDITOR",
                    "NUMERACAO": "NUMERACAO",
                },
            },
        },
    )

    a = _lanc("INCOMPLETO", "10-1")
    b = _lanc("OK", "10-2")
    c = _lanc("BLOQUEIO", "10-3")

    calls: list[str] = []

    def fake_processar(automator, connector, lanc, *, indice, total):
        calls.append(lanc.paciente_nome)
        if lanc.paciente_nome == "INCOMPLETO":
            raise DadosIncompletosError("faltam dados", motivo="faltam: sexo")
        if lanc.paciente_nome == "BLOQUEIO":
            raise ApacBlockedError("tela errada")
        return None

    with (
        patch("apac_bot.apac.listar_lancamentos_a_partir", return_value=[a, b, c]),
        patch("apac_bot.apac.filtrar_pendentes_lote") as mock_filtro,
        patch("apac_bot.apac.ApacAutomator") as MockAutomator,
        patch("apac_bot.apac.build_connector") as mock_build,
        patch(
            "apac_bot.apac._processar_paciente_open_apac",
            side_effect=fake_processar,
        ),
    ):
        mock_filtro.return_value = ([a, b, c], [], [])
        automator = MagicMock()
        MockAutomator.return_value = automator
        mock_build.return_value = MagicMock()

        with pytest.raises(ApacBlockedError, match="tela errada"):
            open_apac_session(cfg)

    assert calls == ["INCOMPLETO", "OK", "BLOQUEIO"]
    store = ProgressStore(tmp_path / "progress.db")
    rec_a = store.get(a.clinica_id, a.identidade)
    rec_b = store.get(b.clinica_id, b.identidade)
    rec_c = store.get(c.clinica_id, c.identidade)
    assert rec_a is not None
    assert rec_a.estado == EstadoLancamento.AGUARDANDO_REVISAO
    assert "sexo" in (rec_a.motivo or "")
    assert rec_b is not None
    assert rec_b.estado == EstadoLancamento.CONCLUIDO
    assert rec_c is not None
    assert rec_c.estado == EstadoLancamento.ERRO
