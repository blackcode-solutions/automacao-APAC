from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Garante import quando executado via PYTHONPATH=src
if __name__ == "__main__" and str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apac_bot.apac import ApacBlockedError, open_apac_session
from apac_bot.config import ConfigError, load_config
from apac_bot.connectors.biodata import BiodataMappingError, open_biodata_session
from apac_bot.logging_safe import setup_logging
from apac_bot.pipeline import PipelineError, cmd_fetch, cmd_run, cmd_status
from apac_bot.sheet import SheetError, create_example_workbook


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default="config.json",
        help="Caminho do JSON de configuração (padrão: config.json)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apac_bot",
        description="Automação local APAC + consulta de origem (BIODATA/mock).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Valida configuração e planilha")
    _add_config_arg(p_val)
    p_val.add_argument("--planilha", default=None, help="Override do caminho da planilha")

    p_fetch = sub.add_parser("fetch", help="Consulta origem e registra progresso")
    _add_config_arg(p_fetch)
    p_fetch.add_argument("--planilha", default=None)
    p_fetch.add_argument("--limit", type=int, default=None)

    p_run = sub.add_parser("run", help="Executa fluxo (dry-run por padrão)")
    _add_config_arg(p_run)
    p_run.add_argument("--planilha", default=None)
    p_run.add_argument("--limit", type=int, default=None)
    mode = p_run.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simula sem digitar no APAC (padrão)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Tenta enviar teclas ao APAC (exige mapeamento completo)",
    )

    p_status = sub.add_parser("status", help="Mostra resumo do progresso (SQLite)")
    _add_config_arg(p_status)

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

    p_apac = sub.add_parser(
        "open-apac",
        help="Abre o APAC Magnético (APAC.exe) se necessário e foca a janela",
    )
    _add_config_arg(p_apac)

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

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    planilha = Path(args.planilha) if getattr(args, "planilha", None) else None

    try:
        if args.command == "validate":
            from apac_bot.pipeline import validate_all

            validate_all(cfg, planilha)
            log.info("Validação concluída com sucesso.")
            return 0
        if args.command == "fetch":
            return cmd_fetch(cfg, planilha=planilha, limit=args.limit)
        if args.command == "run":
            dry_run = not bool(args.live)
            return cmd_run(
                cfg,
                planilha=planilha,
                limit=args.limit,
                dry_run=dry_run,
            )
        if args.command == "status":
            return cmd_status(cfg)
        if args.command == "open-biodata":
            open_biodata_session(cfg)
            return 0
        if args.command == "open-apac":
            open_apac_session(cfg)
            return 0
    except (BiodataMappingError, ApacBlockedError) as exc:
        log.error("%s", exc)
        return 2
    except (ConfigError, SheetError, PipelineError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        log.error("Interrompido pelo usuário (Ctrl+C).")
        return 130

    parser.error(f"Comando desconhecido: {args.command}")
    return 2
