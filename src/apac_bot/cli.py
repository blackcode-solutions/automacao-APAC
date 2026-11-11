from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Garante import quando executado via PYTHONPATH=src
if __name__ == "__main__" and str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apac_bot.config import AppConfig, ConfigError, load_config
from apac_bot.connectors.biodata import BiodataMappingError, open_biodata_session
from apac_bot.connectors.biodata_api import BiodataApiError
from apac_bot.license import LicenseError, ensure_license
from apac_bot.logging_safe import setup_logging
from apac_bot.pipeline import PipelineError
from apac_bot.set_pipeline import cmd_gerar_set
from apac_bot.sheet import SheetError, create_example_workbook

# Comandos que exigem licença ativa (ou grace offline).
_LICENSE_GATED = frozenset(
    {
        "validate",
        "open-biodata",
        "gerar-set",
    }
)


def _require_license(cfg: AppConfig, log) -> int | None:
    """Retorna código de saída se bloqueado; None se ok."""
    try:
        result = ensure_license(cfg)
    except LicenseError as exc:
        log.error("[license] %s", exc)
        return 2
    if result.source == "cache":
        log.warning("[license] %s", result.message)
    elif result.source == "online":
        log.info("[license] %s", result.message)
    return None


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default="config.json",
        help="Caminho do JSON de configuração (padrão: config.json)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apac_bot",
        description="SIS DG — geração de arquivo SET/OUT + consulta BIODATA.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Valida configuração e planilha")
    _add_config_arg(p_val)
    p_val.add_argument("--planilha", default=None, help="Override do caminho da planilha")

    p_ex = sub.add_parser(
        "make-example",
        help="Gera data/planilha_exemplo.xlsx com dados fictícios",
    )
    p_ex.add_argument(
        "--out",
        default="data/planilha_exemplo.xlsx",
        help="Caminho de saída",
    )

    p_open = sub.add_parser(
        "open-biodata",
        help="Abre o BIODATA no Chromium para login manual (sem buscar paciente)",
    )
    _add_config_arg(p_open)

    p_set = sub.add_parser(
        "gerar-set",
        help=(
            "Consulta BIODATA e gera arquivo .SET (layout INTERNO); "
            "limite via export_set.limite_pacientes"
        ),
    )
    _add_config_arg(p_set)
    p_set.add_argument("--planilha", default=None)
    p_set.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override de export_set.limite_pacientes",
    )
    p_set.add_argument(
        "--somente-falhas",
        "--completar-erros",
        action="store_true",
        dest="somente_falhas",
        help="Reprocessa só ERRO/AGUARDANDO_REVISAO e mescla no SET parcial",
    )

    p_ui = sub.add_parser(
        "ui",
        help="Abre a interface desktop (CustomTkinter) para config e lote",
    )
    _add_config_arg(p_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    log = setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "make-example":
        out = Path(args.out)
        create_example_workbook(out)
        log.info("Planilha fictícia criada: %s", out)
        return 0

    if args.command == "ui":
        from apac_bot.ui.app import run_ui

        run_ui(args.config)
        return 0

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    if args.command in _LICENSE_GATED:
        blocked = _require_license(cfg, log)
        if blocked is not None:
            return blocked

    planilha = Path(args.planilha) if getattr(args, "planilha", None) else None

    try:
        if args.command == "validate":
            from apac_bot.pipeline import validate_all

            validate_all(cfg, planilha)
            log.info("Validação concluída com sucesso.")
            return 0
        if args.command == "open-biodata":
            open_biodata_session(cfg)
            return 0
        if args.command == "gerar-set":
            return cmd_gerar_set(
                cfg,
                planilha=planilha,
                limit=args.limit,
                somente_falhas=bool(getattr(args, "somente_falhas", False)),
            )
    except (BiodataMappingError, BiodataApiError) as exc:
        log.error("%s", exc)
        return 2
    except (ConfigError, SheetError, PipelineError) as exc:
        log.error("%s", exc)
        return 2
    except LicenseError as exc:
        log.error("[license] %s", exc)
        return 2
    except KeyboardInterrupt:
        log.error("Interrompido pelo usuário (Ctrl+C).")
        return 130

    parser.error(f"Comando desconhecido: {args.command}")
    return 2
