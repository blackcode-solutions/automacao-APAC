"""Conector Eyecare: dados apenas da planilha local de pacientes."""

from __future__ import annotations

from typing import Optional

from apac_bot.config import AppConfig
from apac_bot.icare_pacientes import IcarePacientesIndex, carregar_icare_pacientes
from apac_bot.models import PacienteDados


class EyecareConnector:
    """Consulta pacientes em planilha_pacientes (sem portal Eyecare)."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        index: Optional[IcarePacientesIndex] = None,
    ):
        self._cfg = cfg
        self._index = index if index is not None else carregar_icare_pacientes(cfg)
        self._ultimo: Optional[PacienteDados] = None

    def ler_cadastro_aberto(self) -> Optional[PacienteDados]:
        return self._ultimo

    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        return self.buscar_por_prontuario(id_paciente)

    def buscar_por_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        pac = self._index.get_prontuario(prontuario)
        if pac is not None:
            self._ultimo = pac
        return pac

    def buscar_por_nome(
        self,
        nome: str,
        prontuario: Optional[str] = None,
    ) -> list[PacienteDados]:
        lista = self._index.buscar_nome(nome, prontuario=prontuario)
        if len(lista) == 1:
            self._ultimo = lista[0]
        return lista

    def close(self) -> None:
        return None


IcareSheetConnector = EyecareConnector
