from __future__ import annotations

from typing import Optional

from apac_bot.models import PacienteDados

# Pacientes fictícios — apenas para testes do fluxo.
_PACIENTES: list[PacienteDados] = [
    PacienteDados(
        id_paciente="BIO-1001",
        cpf="529.982.247-25",
        cns="700000000000001",
        nome="MARIA SILVA FICTICIA",
        nome_mae="ANA SILVA FICTICIA",
        nascimento="01/01/1980",
        endereco="Rua Exemplo, 100 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-1002",
        cpf="390.533.447-05",
        cns="700000000000002",
        nome="JOAO SOUZA FICTICIO",
        nome_mae="MARIA SOUZA FICTICIA",
        nascimento="15/05/1975",
        endereco="Av. Teste, 200 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-1003",
        cpf="153.509.460-56",
        cns="700000000000003",
        nome="ANA COSTA FICTICIA",
        nome_mae="JOANA COSTA FICTICIA",
        nascimento="20/08/1990",
        endereco="Travessa Demo, 30 - Cidade Ficticia",
    ),
    # Dois registros com o mesmo nome para forçar ambiguidade
    PacienteDados(
        id_paciente="BIO-2001",
        cpf="111.444.777-35",
        cns="700000000000004",
        nome="PACIENTE AMBIGUO",
        nome_mae="MAE A FICTICIA",
        nascimento="01/01/1985",
        endereco="Rua A, 1 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-2002",
        cpf="886.415.779-47",
        cns="700000000000005",
        nome="PACIENTE AMBIGUO",
        nome_mae="MAE B FICTICIA",
        nascimento="02/02/1986",
        endereco="Rua B, 2 - Cidade Ficticia",
    ),
]


class MockBiodataConnector:
    def __init__(self, pacientes: Optional[list[PacienteDados]] = None):
        self._pacientes = list(pacientes if pacientes is not None else _PACIENTES)

    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        alvo = id_paciente.strip()
        for p in self._pacientes:
            if p.id_paciente == alvo:
                return p
        return None

    def buscar_por_nome(self, nome: str) -> list[PacienteDados]:
        alvo = " ".join(nome.strip().upper().split())
        return [
            p
            for p in self._pacientes
            if p.nome and " ".join(p.nome.upper().split()) == alvo
        ]

    def close(self) -> None:
        return None
