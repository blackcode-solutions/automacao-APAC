"""Retry de busca apos sessao expirada (nome nao encontrado)."""

from __future__ import annotations

from unittest.mock import MagicMock

from apac_bot.connectors.biodata import BiodataConnector
from apac_bot.models import PacienteDados


def test_buscar_por_nome_recupera_sessao_e_rebusca():
    conn = object.__new__(BiodataConnector)
    conn.cfg = MagicMock()
    conn._page = MagicMock()
    conn._cadastro_aberto = True
    conn._ensure_browser = MagicMock()
    conn._loc = MagicMock(
        return_value={"campo_busca_nome": "#clienteCadastroId-ts-control"}
    )
    paciente = PacienteDados(nome="ELMO", cpf="12345678901")
    conn._buscar_lista_no_dialogo = MagicMock(
        side_effect=[[], [paciente]]
    )
    conn._recuperar_sessao_e_cadastro = MagicMock()

    resultado = BiodataConnector.buscar_por_nome(conn, "ELMO CASTELO")

    assert resultado == [paciente]
    conn._recuperar_sessao_e_cadastro.assert_called_once()
    assert conn._buscar_lista_no_dialogo.call_count == 2


def test_buscar_por_nome_sem_retry_se_ja_achou():
    conn = object.__new__(BiodataConnector)
    conn.cfg = MagicMock()
    conn._page = MagicMock()
    conn._ensure_browser = MagicMock()
    conn._loc = MagicMock(
        return_value={"campo_busca_nome": "#clienteCadastroId-ts-control"}
    )
    paciente = PacienteDados(nome="ELMO", cpf="12345678901")
    conn._buscar_lista_no_dialogo = MagicMock(return_value=[paciente])
    conn._recuperar_sessao_e_cadastro = MagicMock()

    resultado = BiodataConnector.buscar_por_nome(conn, "ELMO")

    assert resultado == [paciente]
    conn._recuperar_sessao_e_cadastro.assert_not_called()
    assert conn._buscar_lista_no_dialogo.call_count == 1


def test_buscar_por_id_recupera_quando_vazio():
    conn = object.__new__(BiodataConnector)
    conn.cfg = MagicMock()
    conn._page = MagicMock()
    conn._ensure_browser = MagicMock()
    conn._loc = MagicMock(
        return_value={
            "campo_busca_id": "#campoId",
            "campo_busca_nome": "#nome",
        }
    )
    paciente = PacienteDados(id_paciente="99", cpf="12345678901")
    conn._buscar_lista_no_dialogo = MagicMock(
        side_effect=[[], [paciente]]
    )
    conn._recuperar_sessao_e_cadastro = MagicMock()

    resultado = BiodataConnector.buscar_por_id(conn, "99")

    assert resultado == paciente
    conn._recuperar_sessao_e_cadastro.assert_called_once()
    assert conn._buscar_lista_no_dialogo.call_count == 2
