"""SQLite de clínicas / licenças."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STATUSES = frozenset({"active", "suspended", "expired"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Clinic:
    clinica_id: str
    nome: str
    license_key: str
    status: str
    valid_until: str
    created_at: str
    updated_at: str
    last_seen_at: Optional[str]


class LicenseStore:
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
                CREATE TABLE IF NOT EXISTS clinics (
                    clinica_id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    license_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT
                )
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_clinic(row: sqlite3.Row) -> Clinic:
        return Clinic(
            clinica_id=row["clinica_id"],
            nome=row["nome"],
            license_key=row["license_key"],
            status=row["status"],
            valid_until=row["valid_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seen_at=row["last_seen_at"],
        )

    def list_all(self) -> list[Clinic]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM clinics ORDER BY nome COLLATE NOCASE"
            ).fetchall()
        return [self._row_to_clinic(r) for r in rows]

    def get(self, clinica_id: str) -> Optional[Clinic]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM clinics WHERE clinica_id = ?",
                (clinica_id,),
            ).fetchone()
        return self._row_to_clinic(row) if row else None

    def get_by_key(self, clinica_id: str, license_key: str) -> Optional[Clinic]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM clinics
                WHERE clinica_id = ? AND license_key = ?
                """,
                (clinica_id, license_key),
            ).fetchone()
        return self._row_to_clinic(row) if row else None

    @staticmethod
    def new_license_key() -> str:
        return str(uuid.uuid4())

    def create(
        self,
        *,
        clinica_id: str,
        nome: str,
        status: str,
        valid_until: str,
        license_key: Optional[str] = None,
    ) -> Clinic:
        if status not in STATUSES:
            raise ValueError(f"status inválido: {status}")
        now = _utc_now()
        key = license_key or self.new_license_key()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clinics (
                    clinica_id, nome, license_key, status, valid_until,
                    created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (clinica_id, nome, key, status, valid_until, now, now),
            )
            conn.commit()
        clinic = self.get(clinica_id)
        if clinic is None:
            raise RuntimeError("[license-db] create failed to read back clinic")
        return clinic

    def update(
        self,
        clinica_id: str,
        *,
        nome: Optional[str] = None,
        status: Optional[str] = None,
        valid_until: Optional[str] = None,
        regenerate_key: bool = False,
    ) -> Optional[Clinic]:
        current = self.get(clinica_id)
        if current is None:
            return None
        if status is not None and status not in STATUSES:
            raise ValueError(f"status inválido: {status}")
        new_nome = nome if nome is not None else current.nome
        new_status = status if status is not None else current.status
        new_until = valid_until if valid_until is not None else current.valid_until
        new_key = self.new_license_key() if regenerate_key else current.license_key
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE clinics SET
                    nome = ?, license_key = ?, status = ?, valid_until = ?,
                    updated_at = ?
                WHERE clinica_id = ?
                """,
                (new_nome, new_key, new_status, new_until, now, clinica_id),
            )
            conn.commit()
        return self.get(clinica_id)

    def touch_last_seen(self, clinica_id: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE clinics SET last_seen_at = ?, updated_at = updated_at
                WHERE clinica_id = ?
                """,
                (now, clinica_id),
            )
            conn.commit()

    def delete(self, clinica_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM clinics WHERE clinica_id = ?",
                (clinica_id,),
            )
            conn.commit()
            return cur.rowcount > 0
