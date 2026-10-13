import json
from pathlib import Path

from apac_bot.cli import main
from apac_bot.config import load_config
from apac_bot.pipeline import cmd_run
from apac_bot.sheet import create_example_workbook


def _prepare(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
    xlsx = tmp_path / "planilha_exemplo.xlsx"
    create_example_workbook(xlsx)
    example["planilha"]["caminho"] = str(xlsx)
    example["progresso"] = {"caminho_db": str(tmp_path / "progress.db")}
    example["sistema_origem"] = "mock"
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_path


def test_validate_and_dry_run(tmp_path: Path):
    cfg_path = _prepare(tmp_path)
    assert main(["validate", "--config", str(cfg_path)]) == 0
    assert main(["fetch", "--config", str(cfg_path), "--limit", "2"]) == 0
    assert main(["run", "--config", str(cfg_path), "--dry-run", "--limit", "2"]) == 0
    assert main(["status", "--config", str(cfg_path)]) == 0


def test_live_bloqueado_sem_passos(tmp_path: Path):
    cfg_path = _prepare(tmp_path)
    code = main(["run", "--config", str(cfg_path), "--live", "--limit", "1"])
    assert code == 2


def test_biodata_bloqueado_por_locators(tmp_path: Path):
    cfg_path = _prepare(tmp_path)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["sistema_origem"] = "biodata"
    raw["biodata"]["navegacao"] = {
        "modulo_atendimento": None,
        "campo_busca_menu": None,
        "item_cadastro_pacientes": None,
    }
    raw["biodata"]["locators"] = {
        k: None for k in (raw.get("biodata", {}).get("locators") or {})
    }
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")
    code = main(["fetch", "--config", str(cfg_path), "--limit", "1"])
    assert code == 2


def test_ambiguidade_na_run(tmp_path: Path):
    cfg_path = _prepare(tmp_path)
    cfg = load_config(cfg_path)
    # Apenas o lançamento ambíguo (4º da planilha exemplo) — limit alto mas filtramos via run
    code = cmd_run(cfg, limit=4, dry_run=True)
    assert code == 0
