from pathlib import Path

from apac_bot.models import EstadoLancamento, Lancamento
from apac_bot.progress import ProgressStore, filtrar_pendentes_lote


def _lanc(num: str = "123-4", auditor: str = "AUD01") -> Lancamento:
    return Lancamento(
        clinica_id="clinica_exemplo",
        numeracao_original=num,
        numeracao_apac=num.replace("-", "/"),
        codigo_original="0412345678",
        codigo_apac="0412345678",
        auditor=auditor,
        paciente_nome="MARIA SILVA FICTICIA",
        id_paciente="BIO-1001",
    )


def test_retomada_nao_reprocessa_concluido(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc()
    store.upsert(lanc, EstadoLancamento.CONCLUIDO, motivo="ok")
    pular, motivo = store.deve_pular(lanc)
    assert pular is True
    assert "concluído" in motivo


def test_detecta_alteracao_entrada(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc(auditor="AUD01")
    store.upsert(lanc, EstadoLancamento.ERRO, motivo="falha")
    lanc2 = _lanc(auditor="AUD99")
    pular, motivo = store.deve_pular(lanc2)
    assert pular is False
    assert motivo is not None
    assert "alterada" in motivo


def test_salvamento_incerto_bloqueia_retry(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc()
    store.upsert(
        lanc,
        EstadoLancamento.SALVAMENTO_INCERTO,
        motivo="Ctrl+C no save",
        precisa_reconciliar=True,
    )
    pular, motivo = store.deve_pular(lanc)
    assert pular is True
    assert "incerto" in motivo
    assert store.get(lanc.clinica_id, lanc.identidade).precisa_reconciliar is True


def test_identidade_nao_usa_linha():
    a = _lanc("999-1")
    a.linha_planilha = 2
    b = _lanc("999-1")
    b.linha_planilha = 99
    assert a.identidade == b.identidade


def test_filtrar_pendentes_pula_concluidos(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    a = _lanc("111-1")
    a.paciente_nome = "AAA"
    b = _lanc("222-2")
    b.paciente_nome = "BBB"
    c = _lanc("333-3")
    c.paciente_nome = "CCC"
    store.upsert(a, EstadoLancamento.CONCLUIDO, motivo="ok")
    store.upsert(b, EstadoLancamento.ERRO, motivo="falha")

    pendentes, pulados, alterados = filtrar_pendentes_lote([a, b, c], store)
    assert [l.paciente_nome for l in pendentes] == ["BBB", "CCC"]
    assert len(pulados) == 1
    assert pulados[0][0].paciente_nome == "AAA"
    assert "concluído" in pulados[0][1]
    assert alterados == []


def test_filtrar_pendentes_entrada_alterada(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc(auditor="AUD01")
    store.upsert(lanc, EstadoLancamento.ERRO, motivo="falha")
    lanc2 = _lanc(auditor="AUD99")
    pendentes, pulados, alterados = filtrar_pendentes_lote([lanc2], store)
    assert pendentes == [lanc2]
    assert pulados == []
    assert alterados == [lanc2]
