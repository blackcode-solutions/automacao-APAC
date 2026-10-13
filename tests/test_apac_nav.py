import json
from pathlib import Path

from apac_bot.apac import ApacAutomator
from apac_bot.config import AppConfig
from apac_bot.models import Lancamento


def _cfg(tmp_path: Path) -> AppConfig:
    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(example), encoding="utf-8")
    return AppConfig(raw=example, path=cfg_path)


def test_navegacao_inicial_dry_run_marca_feita(tmp_path: Path):
    cfg = _cfg(tmp_path)
    assert cfg.apac.get("usar_navegacao_inicial", True)
    auto = ApacAutomator(cfg, dry_run=True)
    auto.navegar_ate_cadastro()
    assert auto._nav_inicial_feita is True
    auto.navegar_ate_cadastro()


def test_navegacao_inicial_desligada(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg.raw["apac"]["usar_navegacao_inicial"] = False
    auto = ApacAutomator(cfg, dry_run=True)
    auto.navegar_ate_cadastro()
    assert auto._nav_inicial_feita is True


def test_run_lancamento_dry_run_nao_exige_passos(tmp_path: Path):
    cfg = _cfg(tmp_path)
    auto = ApacAutomator(cfg, dry_run=True)
    lanc = Lancamento(
        clinica_id="x",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="1",
        codigo_apac="1",
        auditor="a",
        paciente_nome="TESTE",
    )
    result = auto.run_lancamento(lanc)
    assert result.ok
