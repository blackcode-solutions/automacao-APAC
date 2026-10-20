from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class EstadoLancamento(str, Enum):
    PENDENTE = "pendente"
    EM_PROCESSAMENTO = "em_processamento"
    AGUARDANDO_REVISAO = "aguardando_revisao"
    CONCLUIDO = "concluido"
    ERRO = "erro"
    SALVAMENTO_INCERTO = "salvamento_incerto"


@dataclass
class PacienteDados:
    """Dados do paciente na origem. Campos ausentes ficam None — nunca inventar."""

    id_paciente: Optional[str] = None
    cpf: Optional[str] = None
    cns: Optional[str] = None
    nome: Optional[str] = None
    nome_mae: Optional[str] = None
    nascimento: Optional[str] = None
    sexo: Optional[str] = None  # M ou F quando normalizado
    endereco: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    bairro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None

    def campos_preenchidos(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != ""}


@dataclass
class Lancamento:
    clinica_id: str
    numeracao_original: str
    numeracao_apac: str
    codigo_original: str
    codigo_apac: str
    auditor: str
    paciente_nome: str
    id_paciente: Optional[str] = None
    prontuario: Optional[str] = None  # ID clinica (2a planilha) p/ desambiguar BIODATA
    quant: Optional[str] = None
    competencia: Optional[str] = None
    validade: Optional[str] = None
    linha_planilha: Optional[int] = None
    paciente: Optional[PacienteDados] = None
    estado: EstadoLancamento = EstadoLancamento.PENDENTE
    motivo: Optional[str] = None
    # Glaucoma: códigos extras da coluna "Associado a" (entre parênteses).
    codigos_associados: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def identidade(self) -> str:
        """Identidade estável do lançamento (não usa número da linha)."""
        base = f"{self.clinica_id}|{self.numeracao_original}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    def hash_entrada(self) -> str:
        """Hash dos campos relevantes para detectar alteração na retomada."""
        partes = [
            self.clinica_id,
            self.numeracao_original,
            self.codigo_original,
            self.auditor or "",
            self.paciente_nome or "",
            self.id_paciente or "",
            self.prontuario or "",
            self.quant or "",
            self.competencia or "",
            self.validade or "",
        ]
        return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()
