from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apac_bot.models import EstadoLancamento, Lancamento

MOTIVO_ENTRADA_ALTERADA = "entrada alterada desde a última execução"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProgressRecord:
    clinica_id: str
    identidade: str
    numeracao_original: str
    estado: EstadoLancamento
    hash_entrada: str
    motivo: Optional[str]
    precisa_reconciliar: bool
    atualizado_em: str


class ProgressStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lancamentos (
                    clinica_id TEXT NOT NULL,
                    identidade TEXT NOT NULL,
                    numeracao_original TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    hash_entrada TEXT NOT NULL,
                    motivo TEXT,
                    precisa_reconciliar INTEGER NOT NULL DEFAULT 0,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    PRIMARY KEY (clinica_id, identidade)
                )
                """
            )
            conn.commit()

    def get(self, clinica_id: str, identidade: str) -> Optional[ProgressRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM lancamentos
                WHERE clinica_id = ? AND identidade = ?
                """,
                (clinica_id, identidade),
            ).fetchone()
        if row is None:
            return None
        return ProgressRecord(
            clinica_id=row["clinica_id"],
            identidade=row["identidade"],
            numeracao_original=row["numeracao_original"],
            estado=EstadoLancamento(row["estado"]),
            hash_entrada=row["hash_entrada"],
            motivo=row["motivo"],
            precisa_reconciliar=bool(row["precisa_reconciliar"]),
            atualizado_em=row["atualizado_em"],
        )

    def upsert(
        self,
        lanc: Lancamento,
        estado: EstadoLancamento,
        motivo: Optional[str] = None,
        precisa_reconciliar: bool = False,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lancamentos (
                    clinica_id, identidade, numeracao_original, estado,
                    hash_entrada, motivo, precisa_reconciliar, criado_em, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(clinica_id, identidade) DO UPDATE SET
                    numeracao_original = excluded.numeracao_original,
                    estado = excluded.estado,
                    hash_entrada = excluded.hash_entrada,
                    motivo = excluded.motivo,
                    precisa_reconciliar = excluded.precisa_reconciliar,
                    atualizado_em = excluded.atualizado_em
                """,
                (
                    lanc.clinica_id,
                    lanc.identidade,
                    lanc.numeracao_original,
                    estado.value,
                    lanc.hash_entrada(),
                    motivo,
                    1 if precisa_reconciliar else 0,
                    now,
                    now,
                ),
            )
            conn.commit()

    def list_by_clinica(self, clinica_id: str) -> list[ProgressRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM lancamentos
                WHERE clinica_id = ?
                ORDER BY atualizado_em
                """,
                (clinica_id,),
            ).fetchall()
        return [
            ProgressRecord(
                clinica_id=r["clinica_id"],
                identidade=r["identidade"],
                numeracao_original=r["numeracao_original"],
                estado=EstadoLancamento(r["estado"]),
                hash_entrada=r["hash_entrada"],
                motivo=r["motivo"],
                precisa_reconciliar=bool(r["precisa_reconciliar"]),
                atualizado_em=r["atualizado_em"],
            )
            for r in rows
        ]

    def deve_pular(self, lanc: Lancamento) -> tuple[bool, Optional[str]]:
        """
        Retorna (pular, motivo).
        Não reprocessa concluído; bloqueia salvamento_incerto até reconciliação;
        detecta alteração relevante na entrada.
        """
        rec = self.get(lanc.clinica_id, lanc.identidade)
        if rec is None:
            return False, None
        if rec.estado == EstadoLancamento.CONCLUIDO:
            return True, "já concluído"
        if rec.estado == EstadoLancamento.SALVAMENTO_INCERTO or rec.precisa_reconciliar:
            return True, "salvamento incerto — reconcilie no APAC antes de retomar"
        if rec.hash_entrada != lanc.hash_entrada():
            return False, MOTIVO_ENTRADA_ALTERADA
        if rec.estado == EstadoLancamento.AGUARDANDO_REVISAO:
            return True, "aguardando revisão"
        return False, None


def filtrar_pendentes_lote(
    lancamentos: list[Lancamento],
    store: ProgressStore,
) -> tuple[list[Lancamento], list[tuple[Lancamento, str]], list[Lancamento]]:
    """
    Separa a fila em pendentes (a processar) e pulados (com motivo).
    Terceiro retorno: subset de pendentes com entrada alterada (reprocessar).
    """
    pendentes: list[Lancamento] = []
    pulados: list[tuple[Lancamento, str]] = []
    alterados: list[Lancamento] = []
    for lanc in lancamentos:
        pular, motivo = store.deve_pular(lanc)
        if pular:
            pulados.append((lanc, motivo or "pular"))
            continue
        if motivo == MOTIVO_ENTRADA_ALTERADA:
            alterados.append(lanc)
        pendentes.append(lanc)
    return pendentes, pulados, alterados
