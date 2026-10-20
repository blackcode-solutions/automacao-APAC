from apac_bot.apac import (
    VK_TAB,
    _SCAN_TAB,
    _texto_indica_tela_procedimentos,
    decidir_acao_classificacao,
    decidir_acao_equipe,
    decidir_acao_servico,
)
from apac_bot.console_screen import CampoApac


def test_constantes_tab():
    assert VK_TAB == 0x09
    assert _SCAN_TAB == 0x0F


def test_detecta_codigo_procedimento():
    assert _texto_indica_tela_procedimentos("15.12.19.753-0")
    assert _texto_indica_tela_procedimentos("  15.12.19.753-0  ")


def test_detecta_titulo_procedimentos():
    assert _texto_indica_tela_procedimentos("APAC MAGNETICO PROCEDIMENTOS REALIZADOS")
    assert _texto_indica_tela_procedimentos("CID Princ.")


def test_nao_detecta_cep_nem_nome():
    assert not _texto_indica_tela_procedimentos("74000000")
    assert not _texto_indica_tela_procedimentos("74000-000")
    assert not _texto_indica_tela_procedimentos("ELMO CASTELO BRANCO")
    assert not _texto_indica_tela_procedimentos("")


def test_decidir_acao_equipe_ja_em_classificacao():
    assert decidir_acao_equipe(CampoApac.CLASSIFICACAO) == "ja_pulada"
    assert decidir_acao_equipe(CampoApac.SERVICO) == "ja_pulada"
    assert decidir_acao_equipe(CampoApac.EQUIPE) == "tab"
    assert decidir_acao_equipe(CampoApac.CNS_EXECUTANTE) == "avancar"


def test_decidir_acao_servico_e_classificacao():
    assert decidir_acao_servico(CampoApac.CLASSIFICACAO) == "ja_ok"
    assert decidir_acao_servico(CampoApac.SERVICO) == "tab"
    assert decidir_acao_servico(CampoApac.EQUIPE) == "avancar"
    assert decidir_acao_classificacao(CampoApac.CLASSIFICACAO) == "tab"
    assert decidir_acao_classificacao(CampoApac.SERVICO) == "avancar"


def test_motivo_saida_default_12():
    from apac_bot.apac import ApacAutomator
    from apac_bot.config import AppConfig

    cfg = AppConfig(
        raw={
            "clinica_id": "c",
            "dados_fixos": {},
            "apac": {"titulo_janela": "APAC"},
            "planilha": {
                "caminho": "x.xlsx",
                "aba": "A",
                "colunas": {
                    "PACIENTE": "PACIENTE",
                    "COD": "COD.",
                    "AUDITOR": "AUDITOR",
                    "NUMERACAO": "NUMERAÇÃO",
                },
            },
        },
        path=__file__,
    )
    automator = ApacAutomator(cfg, dry_run=True)
    assert (automator._dado_fixo("motivo_saida", "12") or "12") == "12"


def test_data_alta_ultimo_dia_mes_anterior():
    from datetime import date

    from apac_bot.apac import datas_validade_mes_anterior

    # 14/10/2026 -> fim setembro = 30092026
    _inicio, fim = datas_validade_mes_anterior(date(2026, 10, 14))
    assert fim == "30092026"
    # fevereiro bissexto
    _i, fim_fev = datas_validade_mes_anterior(date(2024, 3, 1))
    assert fim_fev == "29022024"


def test_dt_solicitacao_primeiro_dia_mes_anterior():
    from datetime import date

    from apac_bot.apac import _nome_profissional_f1, datas_validade_mes_anterior

    inicio, _fim = datas_validade_mes_anterior(date(2026, 10, 14))
    assert inicio == "01092026"
    assert _nome_profissional_f1("0RCELIO REZENDE") == "0RCELIO REZENDE"
    assert _nome_profissional_f1("ØRCELIO REZENDE") == "0RCELIO REZENDE"
    assert _nome_profissional_f1("José") == "JOSE"


def test_validade_glaucoma_fim_mais_dois_meses():
    from datetime import date

    from apac_bot.apac import datas_validade_mes_anterior

    inicio, fim = datas_validade_mes_anterior(date(2026, 10, 14), fim_offset_meses=2)
    assert inicio == "01092026"
    assert fim == "30112026"


def test_validade_glaucoma_virada_de_ano():
    from datetime import date

    from apac_bot.apac import datas_validade_mes_anterior

    # Em dezembro/2026, base = novembro → fim = janeiro/2027
    inicio, fim = datas_validade_mes_anterior(date(2026, 12, 5), fim_offset_meses=2)
    assert inicio == "01112026"
    assert fim == "31012027"
