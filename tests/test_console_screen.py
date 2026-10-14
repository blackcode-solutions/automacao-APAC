from apac_bot.console_screen import (
    CampoApac,
    TelaApac,
    campo_compativel,
    classificar_tela,
    extrair_valor_campo_linha,
    identificar_campo_linha,
    preview_tela,
)


FIXTURE_MENU = """
CSMG                SISTEMA DE INFORMACOES AMBULATORIAIS
SET/26                        MENU - PRINCIPAL                      13/10/2026
  A.P.A.C.    RELATORIO     EXPORTACAO
  CADASTRO DE APAC
  CONSISTENCIA
"""

FIXTURE_LISTA = """
ATUALIZACAO DE APAC
  3528412345678  ELMO CASTELO
"""

FIXTURE_IDENT = """
IDENTIFICACAO DO PACIENTE
NUMERO APAC .... 3528412345678
NOME ........... ELMO CASTELO BRANCO
NOME DA MAE .... MARIA
DATA DE NASCIMENTO 01011950
"""

FIXTURE_PROC = """
PROCEDIMENTOS REALIZADOS
COD.PROCEDIMENTO  15.12.19.753-0
CID Princ.        Z00
"""


def test_classifica_menu():
    assert classificar_tela(FIXTURE_MENU) == TelaApac.MENU


def test_classifica_lista():
    assert classificar_tela(FIXTURE_LISTA) == TelaApac.LISTA


def test_classifica_identificacao():
    assert classificar_tela(FIXTURE_IDENT) == TelaApac.IDENTIFICACAO


def test_classifica_procedimentos():
    assert classificar_tela(FIXTURE_PROC) == TelaApac.PROCEDIMENTOS
    assert classificar_tela("15.12.19.753-0") == TelaApac.PROCEDIMENTOS


def test_classifica_vazia_desconhecida():
    assert classificar_tela("") == TelaApac.DESCONHECIDA
    assert classificar_tela("   ") == TelaApac.DESCONHECIDA


def test_preview_tela():
    p = preview_tela(FIXTURE_IDENT, max_chars=40)
    assert len(p) <= 40
    assert "IDENTIFIC" in p.upper() or "NUMERO" in p.upper()


def test_extrair_valor_campo_linha():
    assert (
        extrair_valor_campo_linha("║ NOME .... ELMO CASTELO BRANCO          ║")
        == "ELMO CASTELO BRANCO"
    )
    assert extrair_valor_campo_linha("║ CEP ........ 65041235 ║") == "65041235"
    assert extrair_valor_campo_linha("║ BAIRRO ....            ║") == ""
    assert extrair_valor_campo_linha("") == ""
    assert (
        extrair_valor_campo_linha("65041235 LOGRADOURO : 0") == "65041235"
    )
    assert (
        extrair_valor_campo_linha("15/12/1975 SEXO: ETNIA :") == "15/12/1975"
    )
    assert extrair_valor_campo_linha("M ETNIA :") == "M"


def test_identificar_campo_cep_logradouro():
    linha = "65041235 LOGRADOURO : 0"
    assert identificar_campo_linha(linha) == CampoApac.CEP
    assert identificar_campo_linha(linha, cursor_x=0) == CampoApac.CEP
    assert identificar_campo_linha(linha, cursor_x=20) == CampoApac.LOGRADOURO


def test_identificar_campo_nascimento_sexo_etnia():
    linha = "15/12/1975 SEXO: ETNIA :"
    assert identificar_campo_linha(linha) == CampoApac.NASCIMENTO
    assert identificar_campo_linha(linha, cursor_x=0) == CampoApac.NASCIMENTO
    # "SEXO" comeca por volta do indice 11 na string limpa
    assert identificar_campo_linha(linha, cursor_x=12) == CampoApac.SEXO
    assert identificar_campo_linha(linha, cursor_x=20) == CampoApac.ETNIA_RACA


def test_identificar_campo_municipio():
    assert identificar_campo_linha("211130 / SAO LUIS") == CampoApac.MUNICIPIO
    assert identificar_campo_linha("MUNICIPIO .... 211130") == CampoApac.MUNICIPIO


def test_identificar_municipio_raca_mesma_linha_print():
    # Print real: MUNICIPIO + RACA na mesma linha; RACA != ETNIA (linha de baixo)
    linha = (
        "║ MUNICIPIO(Codigo/nome): 211130  /   SAO LUIS             "
        "RACA: 03 ??              ║"
    )
    assert identificar_campo_linha(linha) == CampoApac.MUNICIPIO
    pos_raca = linha.upper().find("RACA")
    assert identificar_campo_linha(linha, cursor_x=20) == CampoApac.MUNICIPIO
    assert identificar_campo_linha(linha, cursor_x=pos_raca) == CampoApac.ETNIA_RACA
    assert extrair_valor_campo_linha(linha, campo=CampoApac.ETNIA_RACA) == "03"
    assert "211130" in extrair_valor_campo_linha(linha, campo=CampoApac.MUNICIPIO)
    # Gate: nao aceitar RACA se identificou MUNICIPIO
    assert (
        campo_compativel(CampoApac.MUNICIPIO, CampoApac.ETNIA_RACA, linha=linha)
        is False
    )
    assert campo_compativel(
        CampoApac.ETNIA_RACA, CampoApac.ETNIA_RACA, linha=linha
    )


def test_identificar_endereco_numero_telefone_email():
    end = "║ ENDERECO     : SAO BENTO                    NUMERO: 07           ║"
    assert identificar_campo_linha(end) == CampoApac.ENDERECO
    assert (
        identificar_campo_linha(end, cursor_x=end.upper().find("NUMERO"))
        == CampoApac.NUMERO
    )
    tel = "║ TELEFONE     : 0           0              E-MAIL :               ║"
    assert identificar_campo_linha(tel) == CampoApac.TELEFONE
    assert (
        identificar_campo_linha(tel, cursor_x=tel.upper().find("E-MAIL"))
        == CampoApac.EMAIL
    )


def test_identificar_campo_telefone_email():
    assert identificar_campo_linha("TELEFONE (DDD) .... 98") == CampoApac.TELEFONE
    assert identificar_campo_linha("EMAIL .... a@b.com") == CampoApac.EMAIL


def test_identificar_campo_etnia_rotulo():
    assert identificar_campo_linha("ETNIA :") == CampoApac.ETNIA_RACA
    assert identificar_campo_linha("RACA .... 03") == CampoApac.ETNIA_RACA


def test_nascimento_sexo_etnia_com_rotulos_print():
    linha = (
        "║ DATA DE NASCIMENTO    : 15/12/1975   SEXO: M         ETNIA :     ║"
    )
    assert identificar_campo_linha(linha) == CampoApac.NASCIMENTO
    assert (
        identificar_campo_linha(linha, cursor_x=linha.upper().find("SEXO"))
        == CampoApac.SEXO
    )
    assert (
        identificar_campo_linha(linha, cursor_x=linha.upper().find("ETNIA"))
        == CampoApac.ETNIA_RACA
    )
    assert (
        extrair_valor_campo_linha(linha, campo=CampoApac.NASCIMENTO) == "15/12/1975"
    )
    assert extrair_valor_campo_linha(linha, campo=CampoApac.SEXO) == "M"


def test_identificar_campo_complemento_bairro_mesma_linha():
    # Buffer real: complemento vazio + bairro na mesma linha (muitos espacos)
    linha = (
        "║ COMPLEMENTO:                   "
        "              BAIRRO: COROADINHO           ║"
    )
    assert identificar_campo_linha(linha) == CampoApac.COMPLEMENTO
    # Cursor no valor do complemento (antes de BAIRRO)
    pos_bai = linha.upper().find("BAIRRO")
    assert identificar_campo_linha(linha, cursor_x=20) == CampoApac.COMPLEMENTO
    assert identificar_campo_linha(linha, cursor_x=pos_bai) == CampoApac.BAIRRO
    assert campo_compativel(
        CampoApac.BAIRRO, CampoApac.COMPLEMENTO, linha=linha
    )
    # Passo BAIRRO nao aceita so porque o rotulo aparece na linha
    assert (
        campo_compativel(CampoApac.COMPLEMENTO, CampoApac.BAIRRO, linha=linha)
        is False
    )


def test_identificar_campo_responsavel_truncado():
    # Buffer real do Magnético trunca o rotulo
    linha = "║ NOME DO RES: O MESMO                                                         ║"
    assert identificar_campo_linha(linha) == CampoApac.RESPONSAVEL
    assert campo_compativel(
        CampoApac.RESPONSAVEL, CampoApac.RESPONSAVEL, linha=linha
    )
    # Nao confundir com NOME do paciente
    assert identificar_campo_linha("NOME .... ELMO CASTELO") == CampoApac.NOME


def test_campo_compativel_multirotulo_etnia():
    linha = "15/12/1975 SEXO: ETNIA :"
    # Sem cx a identificacao cai em NASCIMENTO, mas o passo RACA aceita a linha
    atual = identificar_campo_linha(linha)
    assert atual == CampoApac.NASCIMENTO
    assert campo_compativel(atual, CampoApac.ETNIA_RACA, linha=linha)
    assert campo_compativel(CampoApac.TELEFONE, CampoApac.ETNIA_RACA, linha="TELEFONE 98") is False
