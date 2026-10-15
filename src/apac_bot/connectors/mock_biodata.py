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
        sexo="F",
        endereco="Rua Exemplo, 100 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-1002",
        cpf="390.533.447-05",
        cns="700000000000002",
        nome="JOAO SOUZA FICTICIO",
        nome_mae="MARIA SOUZA FICTICIA",
        nascimento="15/05/1975",
        sexo="M",
        endereco="Av. Teste, 200 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-1003",
        cpf="153.509.460-56",
        cns="700000000000003",
        nome="ANA COSTA FICTICIA",
        nome_mae="JOANA COSTA FICTICIA",
        nascimento="20/08/1990",
        sexo="F",
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
        sexo="F",
        endereco="Rua A, 1 - Cidade Ficticia",
    ),
    PacienteDados(
        id_paciente="BIO-2002",
        cpf="886.415.779-47",
        cns="700000000000005",
        nome="PACIENTE AMBIGUO",
        nome_mae="MAE B FICTICIA",
        nascimento="02/02/1986",
        sexo="M",
        endereco="Rua B, 2 - Cidade Ficticia",
    ),
]


class MockBiodataConnector:
    def __init__(self, pacientes: Optional[list[PacienteDados]] = None):
        self._pacientes = list(pacientes if pacientes is not None else _PACIENTES)
        self._ultimo: Optional[PacienteDados] = None

    def ler_cadastro_aberto(self) -> Optional[PacienteDados]:
        """Simula cadastro ja aberto: devolve o ultimo resolvido (sem nova busca)."""
        return self._ultimo

    def buscar_por_id(self, id_paciente: str) -> Optional[PacienteDados]:
        return self.buscar_por_prontuario(id_paciente)

    def buscar_por_prontuario(self, prontuario: str) -> Optional[PacienteDados]:
        alvo = (prontuario or "").strip()
        pront = "".join(ch for ch in alvo if ch.isdigit())
        for p in self._pacientes:
            if not p.id_paciente:
                continue
            if p.id_paciente == alvo:
                self._ultimo = p
                return p
            if pront and "".join(ch for ch in p.id_paciente if ch.isdigit()) == pront:
                self._ultimo = p
                return p
        return None

    def buscar_por_nome(
        self,
        nome: str,
        prontuario: Optional[str] = None,
    ) -> list[PacienteDados]:
        alvo = " ".join(nome.strip().upper().split())
        lista = [
            p
            for p in self._pacientes
            if p.nome and " ".join(p.nome.upper().split()) == alvo
        ]
        if len(lista) <= 1 or not prontuario:
            if len(lista) == 1:
                self._ultimo = lista[0]
            return lista
        pront = "".join(ch for ch in str(prontuario) if ch.isdigit())
        if not pront:
            return lista
        filtrados = [
            p
            for p in lista
            if p.id_paciente
            and "".join(ch for ch in p.id_paciente if ch.isdigit()) == pront
        ]
        out = filtrados if filtrados else lista
        if len(out) == 1:
            self._ultimo = out[0]
        return out

    def close(self) -> None:
        return None
