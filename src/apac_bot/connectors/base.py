from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from apac_bot.models import PacienteDados


@runtime_checkable
class OrigemConnector(Protocol):
    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        """Retorna o paciente pelo identificador único, ou None se não encontrado."""
        ...

    def buscar_por_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        """Busca pelo prontuario/ID clinico no dialogo de pesquisa."""
        ...

    def buscar_por_nome(
        self,
        nome: str,
        prontuario: Optional[str] = None,
    ) -> list[PacienteDados]:
        """Retorna candidatos pelo nome. prontuario opcional desambigua."""
        ...

    def close(self) -> None:
        ...
