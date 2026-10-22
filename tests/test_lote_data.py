"""Testes do merge planilha + progresso para o painel de lote."""

import json
from pathlib import Path

from apac_bot.models import EstadoLancamento, Lancamento
from apac_bot.progress import ProgressRecord
from apac_bot.sheet import create_example_workbook
from apac_bot.ui.lote_data import (
    MSG_ANEXAR_PLANILHA,
    contar_por_estado,
    export_lote_csv,
    filtrar_linhas_lote,
    format_resumo_lote,
    linhas_com_problema,
    load_lote_snapshot,
    merge_lote_rows,
    snapshot_sem_planilha,
    status_label,
)


def _cfg_json_for_lote(tmp_path: Path, *, paciente_inicio: str = "") -> Path:
    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    example["planilha"]["caminho"] = str(tmp_path / "planilha_vazia_ou_outra.xlsx")
    example.setdefault("apac", {})["paciente_inicio"] = paciente_inicio
    example.setdefault("progresso", {})["caminho_db"] = str(tmp_path / "progress.db")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    return cfg_path


def _lanc(
    num: str = "123-4",
    nome: str = "MARIA SILVA",
    id_paciente: str = "BIO-1001",
) -> Lancamento:
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original=num,
        numeracao_apac=num.replace("-", ""),
        codigo_original="0412345678",
        codigo_apac="0412345678",
        auditor="AUD01",
        paciente_nome=nome,
        id_paciente=id_paciente,
    )


def _rec(
    lanc: Lancamento,
    estado: EstadoLancamento,
    motivo: str | None = None,
    atualizado_em: str = "2026-01-01T00:00:00+00:00",
) -> ProgressRecord:
    return ProgressRecord(
        clinica_id=lanc.clinica_id,
        identidade=lanc.identidade,
        numeracao_original=lanc.numeracao_original,
        estado=estado,
        hash_entrada=lanc.hash_entrada(),
        motivo=motivo,
        precisa_reconciliar=False,
        atualizado_em=atualizado_em,
    )


def test_merge_sem_progresso_fica_pendente():
    fila = [_lanc("123-4"), _lanc("2", nome="JOAO", id_paciente="BIO-2")]
    rows = merge_lote_rows(fila, [])
    assert len(rows) == 2
    assert all(r.estado == EstadoLancamento.PENDENTE for r in rows)
    assert rows[0].prontuario == "BIO-1001"
    assert rows[0].nome == "MARIA SILVA"
    assert rows[0].numero_apac == "1234"
    assert rows[0].highlight is False


def test_merge_aplica_estados_e_highlight():
    a = _lanc("111")
    b = _lanc("222", nome="ANA", id_paciente="P2")
    c = _lanc("333", nome="PEDRO", id_paciente="P3")
    records = [
        _rec(a, EstadoLancamento.CONCLUIDO, "incluido no SET"),
        _rec(b, EstadoLancamento.AGUARDANDO_REVISAO, "cadastro incompleto"),
        _rec(c, EstadoLancamento.EM_PROCESSAMENTO, "buscando BIODATA"),
    ]
    rows = merge_lote_rows([a, b, c], records)
    assert rows[0].estado == EstadoLancamento.CONCLUIDO
    assert rows[0].highlight is False
    assert rows[1].estado == EstadoLancamento.AGUARDANDO_REVISAO
    assert rows[1].highlight is True
    assert rows[2].estado == EstadoLancamento.EM_PROCESSAMENTO
    assert rows[2].highlight is True
    assert status_label(rows[0].estado) == "Concluído"
    assert status_label(rows[1].estado) == "Em revisão"


def test_load_snapshot_config_ausente_retorna_erro(tmp_path: Path):
    snap = load_lote_snapshot(tmp_path / "nao_existe.json")
    assert snap.total == 0
    assert snap.rows == ()
    assert snap.erro is not None
    assert "não encontrado" in snap.erro.lower() or "encontrado" in snap.erro.lower()


def test_contar_por_estado_e_linhas_com_problema():
    a = _lanc("111")
    b = _lanc("222", nome="ANA", id_paciente="P2")
    c = _lanc("333", nome="PEDRO", id_paciente="P3")
    d = _lanc("444", nome="LIA", id_paciente="P4")
    records = [
        _rec(a, EstadoLancamento.CONCLUIDO, "incluido no SET"),
        _rec(b, EstadoLancamento.AGUARDANDO_REVISAO, "faltam: cpf, nome_mae"),
        _rec(c, EstadoLancamento.ERRO, "timeout BIODATA"),
        _rec(d, EstadoLancamento.SALVAMENTO_INCERTO, "confirme no APAC"),
    ]
    rows = merge_lote_rows([a, b, c, d], records)
    contagem = contar_por_estado(rows)
    assert contagem[EstadoLancamento.CONCLUIDO] == 1
    assert contagem[EstadoLancamento.AGUARDANDO_REVISAO] == 1
    assert contagem[EstadoLancamento.ERRO] == 1
    assert contagem[EstadoLancamento.SALVAMENTO_INCERTO] == 1

    problemas = linhas_com_problema(rows)
    assert len(problemas) == 3
    assert {r.estado for r in problemas} == {
        EstadoLancamento.AGUARDANDO_REVISAO,
        EstadoLancamento.ERRO,
        EstadoLancamento.SALVAMENTO_INCERTO,
    }
    resumo = format_resumo_lote(rows)
    assert "4 total" in resumo
    assert "1 concluído" in resumo
    assert "1 erro" in resumo


def test_export_lote_csv_preserva_motivo_com_virgula_e_acentos(tmp_path: Path):
    a = _lanc("111", nome="JOSÉ ÁVILA")
    records = [
        _rec(a, EstadoLancamento.ERRO, "faltam: cpf, nome_mae"),
    ]
    rows = tuple(merge_lote_rows([a], records))
    out = tmp_path / "relatorio.csv"
    export_lote_csv(out, rows)
    raw = out.read_text(encoding="utf-8-sig")
    lines = raw.strip().splitlines()
    assert lines[0] == "prontuario,nome,numero_apac,status,motivo"
    assert "JOSÉ ÁVILA" in raw
    assert "faltam: cpf, nome_mae" in raw
    assert "Erro" in raw


def test_filtrar_linhas_lote_por_nome_status_e_query_vazia():
    a = _lanc("111", nome="MARIA SILVA", id_paciente="BIO-1")
    b = _lanc("222", nome="JOSE CARVALHO", id_paciente="BIO-2")
    c = _lanc("333", nome="ANA COSTA", id_paciente="BIO-3")
    records = [
        _rec(a, EstadoLancamento.CONCLUIDO),
        _rec(b, EstadoLancamento.ERRO, "faltam: cpf"),
        _rec(c, EstadoLancamento.PENDENTE),
    ]
    rows = tuple(merge_lote_rows([a, b, c], records))

    assert filtrar_linhas_lote(rows, "") == rows
    assert filtrar_linhas_lote(rows, "   ") == rows

    por_nome = filtrar_linhas_lote(rows, "jose")
    assert len(por_nome) == 1
    assert por_nome[0].nome == "JOSE CARVALHO"

    por_status = filtrar_linhas_lote(rows, "erro")
    assert len(por_status) == 1
    assert por_status[0].estado == EstadoLancamento.ERRO

    por_pront = filtrar_linhas_lote(rows, "bio-3")
    assert len(por_pront) == 1
    assert por_pront[0].prontuario == "BIO-3"

    por_apac = filtrar_linhas_lote(rows, "222")
    assert len(por_apac) == 1
    assert por_apac[0].numero_apac == "222"


def test_load_snapshot_com_planilha_override_ignora_caminho_do_config(
    tmp_path: Path,
):
    override = tmp_path / "anexada.xlsx"
    create_example_workbook(override)
    cfg_path = _cfg_json_for_lote(tmp_path, paciente_inicio="")

    snap_sem = load_lote_snapshot(cfg_path)
    assert snap_sem.total == 0
    assert snap_sem.erro is not None

    snap = load_lote_snapshot(cfg_path, planilha_override=override)
    assert snap.erro is None
    assert snap.total > 0
    assert len(snap.rows) == snap.total
    assert snap.rows[0].nome == "MARIA SILVA FICTICIA"


def test_load_snapshot_paciente_inicio_vazio_carrega_preview(
    tmp_path: Path,
):
    xlsx = tmp_path / "planilha.xlsx"
    create_example_workbook(xlsx)
    cfg_path = _cfg_json_for_lote(tmp_path, paciente_inicio="")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["planilha"]["caminho"] = str(xlsx)
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")

    snap = load_lote_snapshot(cfg_path)
    assert snap.erro is None
    assert snap.total > 0
    assert all(r.nome for r in snap.rows)
    assert "paciente_inicio" not in (snap.erro or "").lower()


def test_snapshot_sem_planilha_vazio_com_mensagem():
    snap = snapshot_sem_planilha()
    assert snap.rows == ()
    assert snap.total == 0
    assert snap.concluidos == 0
    assert snap.erro is None
    assert snap.mensagem_tabela == MSG_ANEXAR_PLANILHA
    assert "anexe a planilha" in snap.mensagem_tabela.casefold()
