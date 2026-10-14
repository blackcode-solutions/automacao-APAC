from pathlib import Path

from apac_bot.config import load_config
from apac_bot.sheet import (
    carregar_mapa_prontuario,
    nome_chave_prontuario,
    opcao_contem_prontuario,
)


def test_opcao_contem_prontuario():
    assert opcao_contem_prontuario("1763812 SANDRA MARIA PEREIRA SILVA", "1763812")
    assert opcao_contem_prontuario("SANDRA | 1763812", "1763812")
    assert not opcao_contem_prontuario("17638120 OUTRO", "1763812")
    assert not opcao_contem_prontuario("SANDRA SEM ID", "1763812")


def test_nome_chave_prontuario_normaliza():
    assert nome_chave_prontuario("  José   Silva ") == nome_chave_prontuario("JOSE SILVA")


def test_carregar_mapa_sandra_elmo():
    cfg_path = Path("config.json")
    if not cfg_path.is_file():
        cfg_path = Path("config.example.json")
    cfg = load_config(cfg_path)
    if not cfg.planilha_prontuarios.get("caminho"):
        return
    caminho = Path(str(cfg.planilha_prontuarios["caminho"]))
    if not caminho.is_file() and not (cfg.path.parent / caminho).is_file():
        return
    mapa = carregar_mapa_prontuario(cfg)
    assert mapa
    assert mapa[nome_chave_prontuario("SANDRA MARIA PEREIRA SILVA")] == "1763812"
    assert mapa[nome_chave_prontuario("ELMO CASTELO BRANCO DE LEMOS")] == "20152"
