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

FIXTURE_DADOS_COMP = """
DADOS COMPLEMENTARES
C.I.D. PRINCIPAL ....
SECUNDARIO ..........
CAUSAS ASSOCIADAS ...
INFORME O C.I.D. PRINCIPAL - F1=AJUDA
"""

FIXTURE_SOLICITACAO = """
SOLICITACAO / AUTORIZACAO
CARATER ATEND. ....
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


def test_classifica_dados_complementares_nao_procedimentos():
    assert classificar_tela(FIXTURE_DADOS_COMP) == TelaApac.DADOS_COMPLEMENTARES
    # Sem "PROCEDIMENTOS REALIZADOS": C.I.D. PRINCIPAL nao deve virar PROCEDIMENTOS
    assert (
        classificar_tela("DADOS COMPLEMENTARES\nC.I.D. PRINCIPAL")
        == TelaApac.DADOS_COMPLEMENTARES
    )


def test_classifica_solicitacao():
    assert classificar_tela(FIXTURE_SOLICITACAO) == TelaApac.SOLICITACAO
    assert classificar_tela("CARATER ATEND. : 01") == TelaApac.SOLICITACAO


def test_identificar_cid_principal():
    linha = "C.I.D. PRINCIPAL ...."
    assert identificar_campo_linha(linha) == CampoApac.CID_PRINCIPAL
    assert campo_compativel(
        CampoApac.CID_PRINCIPAL, CampoApac.CID_PRINCIPAL, linha=linha
    )


def test_identificar_campos_solicitacao():
    assert (
        identificar_campo_linha("CARATER ATEND. : 01")
        == CampoApac.CARATER_ATEND
    )
    assert campo_compativel(
        CampoApac.CARATER_ATEND,
        CampoApac.CARATER_ATEND,
        linha="CARATER ATEND. : 01",
    )
    assert (
        identificar_campo_linha("DT.SOLICITACAO : 01/09/2026")
        == CampoApac.DT_SOLICITACAO
    )
    assert (
        identificar_campo_linha("DT.AUTORIZACAO : 01/09/2026")
        == CampoApac.DT_AUTORIZACAO
    )
    assert (
        identificar_campo_linha("COD.ORGAO EMISS : M211130001")
        == CampoApac.COD_ORGAO_EMISS
    )
    assert campo_compativel(
        CampoApac.COD_ORGAO_EMISS,
        CampoApac.COD_ORGAO_EMISS,
        linha="COD.ORGAO EMISS : M211130001",
    )
    # CNS generico (solicitacao) vs CNS EXECUTANTE
    assert identificar_campo_linha("CNS : 705609469670213") == CampoApac.CNS_SOLICITANTE
    assert campo_compativel(
        CampoApac.CNS_SOLICITANTE,
        CampoApac.CNS_AUTORIZADOR,
        linha="CNS : 708107527671032",
    )
    assert identificar_campo_linha(
        "CNS Executante .... 701003891196892"
    ) == CampoApac.CNS_EXECUTANTE


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


def test_identificar_cod_procedimento():
    linha = "Cod. Procedimento .. . . -"
    assert identificar_campo_linha(linha) == CampoApac.COD_PROCEDIMENTO
    assert campo_compativel(
        CampoApac.COD_PROCEDIMENTO, CampoApac.COD_PROCEDIMENTO, linha=linha
    )
    # Mascara vazia sem rotulo (foco default apos Enter da RACA)
    assert campo_compativel(
        CampoApac.DESCONHECIDO, CampoApac.COD_PROCEDIMENTO, linha=".. . . -"
    )


def test_identificar_campos_procedimentos_bloco():
    assert identificar_campo_linha("C.B.O. .... 225265") == CampoApac.CBO
    assert identificar_campo_linha("Quantidade .... 1") == CampoApac.QUANTIDADE
    assert (
        identificar_campo_linha("CNS Executante .... 701003891196892")
        == CampoApac.CNS_EXECUTANTE
    )
    assert identificar_campo_linha("Equipe ....") == CampoApac.EQUIPE
    assert identificar_campo_linha("Servico .... 123") == CampoApac.SERVICO
    assert identificar_campo_linha("Classif. .... 01") == CampoApac.CLASSIFICACAO


def test_identificar_motivo_saida():
    linha = "MOTIVO SAIDA : 0     DATA ALTA/OBITO/TRANSF./MUDANCA PROCED.:  /  /"
    assert identificar_campo_linha(linha) == CampoApac.MOTIVO_SAIDA
    assert campo_compativel(
        CampoApac.MOTIVO_SAIDA, CampoApac.MOTIVO_SAIDA, linha=linha
    )


def test_identificar_data_alta_mesma_linha():
    linha = "MOTIVO SAIDA : 12    DATA ALTA/OBITO/TRANSF./MUDANCA PROCED.:  /  /"
    assert identificar_campo_linha(linha) == CampoApac.MOTIVO_SAIDA
    pos_data = linha.upper().find("DATA ALTA")
    assert (
        identificar_campo_linha(linha, cursor_x=pos_data) == CampoApac.DATA_ALTA
    )
    assert campo_compativel(
        CampoApac.DATA_ALTA, CampoApac.DATA_ALTA, linha=linha
    )


def test_quantidade_cns_mesma_linha():
    linha = "║   │Quantidade  1               CNS Executante     "
    assert identificar_campo_linha(linha) == CampoApac.QUANTIDADE
    assert identificar_campo_linha(linha, cursor_x=10) == CampoApac.QUANTIDADE
    pos_cns = linha.upper().find("CNS")
    assert identificar_campo_linha(linha, cursor_x=pos_cns) == CampoApac.CNS_EXECUTANTE
    # Gate CNS nao aceita se identificou QUANTIDADE
    assert (
        campo_compativel(CampoApac.QUANTIDADE, CampoApac.CNS_EXECUTANTE, linha=linha)
        is False
    )
    assert campo_compativel(
        CampoApac.CNS_EXECUTANTE, CampoApac.CNS_EXECUTANTE, linha=linha
    )


def test_campo_compativel_multirotulo_etnia():
    linha = "15/12/1975 SEXO: ETNIA :"
    # Sem cx cai em NASCIMENTO — NAO aceitar como SEXO/ETNIA (exige cx)
    atual = identificar_campo_linha(linha)
    assert atual == CampoApac.NASCIMENTO
    assert (
        campo_compativel(atual, CampoApac.ETNIA_RACA, linha=linha) is False
    )
    assert campo_compativel(atual, CampoApac.SEXO, linha=linha) is False
    assert campo_compativel(
        CampoApac.SEXO, CampoApac.SEXO, linha=linha
    )
    assert campo_compativel(
        CampoApac.ETNIA_RACA, CampoApac.ETNIA_RACA, linha=linha
    )
    assert campo_compativel(CampoApac.TELEFONE, CampoApac.ETNIA_RACA, linha="TELEFONE 98") is False
