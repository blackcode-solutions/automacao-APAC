from pathlib import Path

from apac_bot.models import EstadoLancamento
from apac_bot.progress import ProgressStore

from tests.test_progress import _lanc


def test_clear_clinica_remove_todos_registros(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc_a = _lanc("111-1")
    lanc_b = _lanc("222-2", auditor="AUD02")
    store.upsert(lanc_a, EstadoLancamento.CONCLUIDO, motivo="ok")
    store.upsert(lanc_b, EstadoLancamento.ERRO, motivo="falha")
    assert len(store.list_by_clinica(lanc_a.clinica_id)) == 2

    removed = store.clear_clinica(lanc_a.clinica_id)
    assert removed == 2
    assert store.list_by_clinica(lanc_a.clinica_id) == []
    assert store.get(lanc_a.clinica_id, lanc_a.identidade) is None


def test_clear_clinica_nao_afeta_outra_clinica(tmp_path: Path):
    from apac_bot.models import Lancamento

    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc("1-1")
    outro = Lancamento(
        clinica_id="outra_clinica",
        numeracao_original="2-2",
        numeracao_apac="22",
        codigo_original="0412345678",
        codigo_apac="0412345678",
        auditor="AUD02",
        paciente_nome="OUTRO",
        id_paciente="BIO-2",
    )
    store.upsert(lanc, EstadoLancamento.CONCLUIDO)
    store.upsert(outro, EstadoLancamento.CONCLUIDO)

    assert store.clear_clinica(lanc.clinica_id) == 1
    assert len(store.list_by_clinica(outro.clinica_id)) == 1
