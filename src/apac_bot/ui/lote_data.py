"""Monta linhas do painel de lote: planilha + ProgressStore."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, config_dir, load_config, resolve_path
from apac_bot.models import EstadoLancamento, Lancamento
from apac_bot.progress import ProgressRecord, ProgressStore
from apac_bot.sheet import SheetError, listar_lancamentos_a_partir

STATUS_LABELS: dict[EstadoLancamento, str] = {
    EstadoLancamento.CONCLUIDO: "Concluído",
    EstadoLancamento.AGUARDANDO_REVISAO: "Em revisão",
    EstadoLancamento.EM_PROCESSAMENTO: "Em processamento",
    EstadoLancamento.PENDENTE: "Pendente",
    EstadoLancamento.ERRO: "Erro",
    EstadoLancamento.SALVAMENTO_INCERTO: "Incerto",
}

ESTADOS_PROBLEMA: frozenset[EstadoLancamento] = frozenset(
    {
        EstadoLancamento.ERRO,
        EstadoLancamento.AGUARDANDO_REVISAO,
        EstadoLancamento.SALVAMENTO_INCERTO,
    }
)

_CSV_HEADERS = (
    "prontuario",
    "nome",
    "numero_apac",
    "status",
    "motivo",
)


@dataclass(frozen=True, slots=True)
class LoteRow:
    identidade: str
    prontuario: str
    nome: str
    numero_apac: str
    estado: EstadoLancamento
    motivo: Optional[str]
    highlight: bool


@dataclass(frozen=True, slots=True)
class LoteSnapshot:
    rows: tuple[LoteRow, ...]
    concluidos: int
    total: int
    ultima_etapa: str
    erro: Optional[str] = None


def status_label(estado: EstadoLancamento) -> str:
    return STATUS_LABELS.get(estado, estado.value)


def contar_por_estado(
    rows: Sequence[LoteRow],
) -> dict[EstadoLancamento, int]:
    contagem: dict[EstadoLancamento, int] = {}
    for row in rows:
        contagem[row.estado] = contagem.get(row.estado, 0) + 1
    return contagem


def linhas_com_problema(rows: Sequence[LoteRow]) -> tuple[LoteRow, ...]:
    return tuple(r for r in rows if r.estado in ESTADOS_PROBLEMA)


def filtrar_linhas_lote(
    rows: Sequence[LoteRow],
    query: str,
) -> tuple[LoteRow, ...]:
    """Filtra por substring em prontuário, nome, nº APAC ou status (casefold)."""
    q = query.casefold().strip()
    if not q:
        return tuple(rows)
    out: list[LoteRow] = []
    for row in rows:
        haystacks = (
            row.prontuario,
            row.nome,
            row.numero_apac,
            status_label(row.estado),
            row.estado.value,
        )
        if any(q in (field or "").casefold() for field in haystacks):
            out.append(row)
    return tuple(out)


def format_resumo_lote(rows: Sequence[LoteRow]) -> str:
    """Texto curto para o cabeçalho do relatório do lote."""
    total = len(rows)
    if total == 0:
        return "0 total"
    contagem = contar_por_estado(rows)
    partes = [f"{total} total"]
    for estado in (
        EstadoLancamento.CONCLUIDO,
        EstadoLancamento.AGUARDANDO_REVISAO,
        EstadoLancamento.ERRO,
        EstadoLancamento.SALVAMENTO_INCERTO,
        EstadoLancamento.PENDENTE,
        EstadoLancamento.EM_PROCESSAMENTO,
    ):
        n = contagem.get(estado, 0)
        if n <= 0:
            continue
        label = status_label(estado).lower()
        if estado == EstadoLancamento.ERRO and n != 1:
            label = "erros"
        elif estado == EstadoLancamento.CONCLUIDO and n != 1:
            label = "concluídos"
        elif estado == EstadoLancamento.PENDENTE and n != 1:
            label = "pendentes"
        partes.append(f"{n} {label}")
    return " · ".join(partes)


def export_lote_csv(path: Path, rows: Sequence[LoteRow]) -> None:
    """Grava CSV UTF-8 com BOM; motivo vazio vira string vazia."""
    dest = Path(path)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADERS)
        for row in rows:
            writer.writerow(
                [
                    row.prontuario,
                    row.nome,
                    row.numero_apac,
                    status_label(row.estado),
                    row.motivo or "",
                ]
            )


def _limite_fila(cfg: AppConfig) -> int:
    raw = cfg.export_set.get("limite_pacientes", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _store(cfg: AppConfig) -> ProgressStore:
    base = config_dir(cfg)
    return ProgressStore(resolve_path(base, cfg.progresso_db))


def _prontuario(lanc: Lancamento) -> str:
    return (lanc.id_paciente or lanc.prontuario or "").strip()


def _numero_apac(lanc: Lancamento) -> str:
    return (lanc.numeracao_apac or lanc.numeracao_original or "").strip()


def _progress_by_id(
    records: list[ProgressRecord],
) -> dict[str, ProgressRecord]:
    return {r.identidade: r for r in records}


def _pick_ultima_etapa(rows: list[LoteRow], by_id: dict[str, ProgressRecord]) -> str:
    """Preferência: em processamento → revisão → último motivo por atualizado_em."""
    for preferred in (
        EstadoLancamento.EM_PROCESSAMENTO,
        EstadoLancamento.AGUARDANDO_REVISAO,
    ):
        for row in rows:
            if row.estado != preferred:
                continue
            if row.motivo:
                return row.motivo
    dated: list[tuple[str, str]] = []
    for row in rows:
        rec = by_id.get(row.identidade)
        if rec is None or not rec.motivo:
            continue
        dated.append((rec.atualizado_em, rec.motivo))
    if not dated:
        return ""
    dated.sort(key=lambda item: item[0], reverse=True)
    return dated[0][1]


def merge_lote_rows(
    fila: list[Lancamento],
    records: list[ProgressRecord],
) -> list[LoteRow]:
    by_id = _progress_by_id(records)
    rows: list[LoteRow] = []
    for lanc in fila:
        rec = by_id.get(lanc.identidade)
        estado = rec.estado if rec is not None else EstadoLancamento.PENDENTE
        motivo = rec.motivo if rec is not None else None
        highlight = estado in {
            EstadoLancamento.EM_PROCESSAMENTO,
            EstadoLancamento.AGUARDANDO_REVISAO,
        }
        rows.append(
            LoteRow(
                identidade=lanc.identidade,
                prontuario=_prontuario(lanc),
                nome=(lanc.paciente_nome or "").strip(),
                numero_apac=_numero_apac(lanc),
                estado=estado,
                motivo=motivo,
                highlight=highlight,
            )
        )
    return rows


def _fila_para_painel(
    cfg: AppConfig, planilha_override: Optional[Path] = None
) -> list[Lancamento]:
    """
    Fila exibida no painel: a partir de paciente_inicio se configurado;
    senão todos os lançamentos ativos (mesmo fallback de listar_lancamentos_a_partir).
    """
    return listar_lancamentos_a_partir(cfg, planilha_override)


def load_lote_snapshot(
    config_path: Path,
    *,
    planilha_override: Optional[Path] = None,
    aba_glaucoma_override: Optional[str] = None,
) -> LoteSnapshot:
    """
    Lê config + planilha + SQLite e devolve snapshot para o painel.
    Em erro de planilha/config, retorna snapshot vazio com `erro` preenchido
    (não levanta — a UI mostra o aviso).

    planilha_override: path escolhido no Browse (ainda não salvo no config).
    aba_glaucoma_override: aba escolhida no dropdown (ainda não salva).
    """
    path = Path(config_path)
    override = Path(planilha_override) if planilha_override is not None else None
    try:
        cfg = load_config(path)
    except Exception as exc:
        if override is None:
            return LoteSnapshot(
                rows=(),
                concluidos=0,
                total=0,
                ultima_etapa="",
                erro=str(exc),
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cfg = AppConfig(raw=raw, path=path)
        except Exception:
            return LoteSnapshot(
                rows=(),
                concluidos=0,
                total=0,
                ultima_etapa="",
                erro=str(exc),
            )

    if override is not None:
        cfg = cfg.with_planilha(override)
    if aba_glaucoma_override is not None:
        cfg = cfg.with_aba_glaucoma(aba_glaucoma_override)

    try:
        fila = _fila_para_painel(cfg, override)
    except SheetError as exc:
        return LoteSnapshot(
            rows=(),
            concluidos=0,
            total=0,
            ultima_etapa="",
            erro=str(exc),
        )

    lim = _limite_fila(cfg)
    if lim > 0:
        fila = fila[:lim]

    try:
        store = _store(cfg)
        records = store.list_by_clinica(cfg.clinica_id)
    except Exception as exc:
        return LoteSnapshot(
            rows=(),
            concluidos=0,
            total=len(fila),
            ultima_etapa="",
            erro=f"Progresso indisponível: {exc}",
        )

    rows = merge_lote_rows(fila, records)
    concluidos = sum(1 for r in rows if r.estado == EstadoLancamento.CONCLUIDO)
    by_id = _progress_by_id(records)
    ultima = _pick_ultima_etapa(rows, by_id)
    return LoteSnapshot(
        rows=tuple(rows),
        concluidos=concluidos,
        total=len(rows),
        ultima_etapa=ultima,
        erro=None,
    )
