"""Interface desktop (CustomTkinter) para config e disparo do bot."""

__all__ = ["run_ui"]


def run_ui(config_path: str | None = None) -> None:
    from apac_bot.ui.app import run_ui as _run

    _run(config_path)
