"""Janela CustomTkinter — splash SIS DG + config dinâmica / ações do bot."""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import PhotoImage, filedialog, messagebox
from typing import Any, Optional

import customtkinter as ctk
from PIL import Image

from apac_bot.config import AppConfig, ConfigError, load_config
from apac_bot.license import LicenseError, ensure_license, license_enabled
from apac_bot.sheet import SheetError, listar_abas_faturamento_glaucoma
from apac_bot.ui import theme
from apac_bot.ui.config_io import (
    CLINICAS_POR_SISTEMA,
    CNES_UI_KEYS,
    DADOS_FIXOS_LABELS,
    DADOS_FIXOS_UI_KEYS,
    MODALIDADE_GLAUCOMA,
    MODALIDADE_PADRAO,
    MODALIDADES_UI,
    SISTEMAS_UI,
    ConfigIoError,
    UiFormData,
    aplicar_defaults_clinica,
    default_config_path,
    load_form,
    modalidade_ui_label,
    normalizar_modalidade,
    normalizar_sistema_origem,
    save_form,
    save_license_key,
    save_modalidade,
    secrets_missing,
    secoes_para_modalidade,
    sistema_ui_label,
    validate_form,
)
from apac_bot.ui.lote_data import (
    LoteSnapshot,
    contagem_falhas_completar,
    linhas_com_problema,
    load_lote_snapshot,
    reset_lote_operacional,
    snapshot_sem_planilha,
    tem_falhas_completar,
)
from apac_bot.ui.lote_panel import (
    HistoricoLogWindow,
    LotePanel,
    RelatorioLoteWindow,
    SetPreviewWindow,
)

# Marca / splash
APP_NAME = "SIS DG"
ABA_GLAUCOMA_TODAS = "Todas as abas"
APP_TAGLINE = "Sistema de Inteligência em Saúde DG"
APP_VERSION = "1.0.0"
BRAND_FG = "#1a2a38"
BRAND_ACCENT = "#103055"
SPLASH_BG = "#ffffff"

# Estilos da splash welcome. btn_rely ≈ posição do CTA na arte.
SPLASH_META: dict = {
    "files": ("splash_welcome.png", "splash_welcome.jpg"),
    "window_bg": SPLASH_BG,
    "btn_fg": BRAND_ACCENT,
    "btn_hover": "#0a2038",
    "btn_text": "#ffffff",
    "badge_fg": BRAND_ACCENT,
    "badge_text": "#ffffff",
    "btn_rely": 0.63,
}

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

log = logging.getLogger(__name__)

WINDOW_ICON_FILE = "icon_dg.png"


def _assets_dir() -> Path:
    from apac_bot.runtime_paths import ui_assets_dir

    return ui_assets_dir()


def _splash_bg_path() -> Optional[Path]:
    """Resolve PNG (preferido) ou JPG da splash welcome."""
    assets = _assets_dir()
    for name in SPLASH_META["files"]:
        path = assets / name
        if path.is_file():
            return path
    return None


def _window_icon_path() -> Optional[Path]:
    path = _assets_dir() / WINDOW_ICON_FILE
    return path if path.is_file() else None


def _pil_fill(
    pil: Image.Image,
    win_w: int,
    win_h: int,
    fill: str | tuple[int, int, int] = "#ffffff",  # unused; API compat
) -> Image.Image:
    """Preenche a janela (cover): mantém proporção, sem achatar a arte."""
    del fill
    win_w, win_h = max(win_w, 1), max(win_h, 1)
    if pil.size == (win_w, win_h):
        return pil.copy()
    scale = max(win_w / max(pil.width, 1), win_h / max(pil.height, 1))
    tw = max(int(pil.width * scale), 1)
    th = max(int(pil.height * scale), 1)
    resized = pil.resize((tw, th), Image.Resampling.LANCZOS)
    left = max((tw - win_w) // 2, 0)
    top = max((th - win_h) // 2, 0)
    return resized.crop((left, top, left + win_w, top + win_h))


class ApacBotApp(ctk.CTk):
    def __init__(self, config_path: Optional[Path] = None) -> None:
        super().__init__()
        self.config_path = Path(config_path) if config_path else default_config_path()
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._proc: Optional[subprocess.Popen] = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_buffer: list[str] = []
        self._job_running = False
        self._reenvio_pendentes_em_execucao = False
        self._lote_panel: Optional[LotePanel] = None
        self._historico_win: Optional[HistoricoLogWindow] = None
        self._relatorio_win: Optional[RelatorioLoteWindow] = None
        self._set_preview_win: Optional[SetPreviewWindow] = None
        self._export_cliente_busy = False
        self._lote_poll_after_id: Optional[str] = None
        self._splash_pil: Optional[Image.Image] = None
        self._splash_bg_image: Optional[ctk.CTkImage] = None
        self._splash_bg_label: Optional[ctk.CTkLabel] = None
        self._splash_btn: Optional[ctk.CTkButton] = None
        self._splash_version: Optional[ctk.CTkLabel] = None
        self._splash_mode = False
        self._resize_after_id: Optional[str] = None
        self._last_bg_size: tuple[int, int] = (0, 0)
        self._main_ready = False
        self._planilha_path_ultimo_reset: str = ""
        self._modalidade = MODALIDADE_PADRAO
        self._dados_fixos_cache: dict[str, str] = {}
        self._secoes_host: Optional[ctk.CTkFrame] = None
        self._body: Optional[ctk.CTkScrollableFrame] = None
        self._window_icon: Optional[PhotoImage] = None

        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        self._apply_window_icon()
        # Splash fixa 1024x576 (proporção da arte welcome — evita logo achatada)
        self.geometry("1024x576")
        self.minsize(1024, 576)
        self.maxsize(1024, 576)
        self.resizable(False, False)
        self.configure(fg_color=SPLASH_BG)
        self._show_splash()

    def _apply_window_icon(self) -> None:
        """Ícone da barra de título / taskbar (PNG empacotado)."""
        path = _window_icon_path()
        if path is None:
            log.warning("[ui] ícone da janela ausente: %s", WINDOW_ICON_FILE)
            return
        try:
            # Manter referência: PhotoImage é GC-sensível no Tk
            self._window_icon = PhotoImage(file=str(path))
            self.iconphoto(True, self._window_icon)
        except Exception as exc:
            log.warning("[ui] falha ao aplicar ícone da janela: %s", exc)

    def _clear_root(self) -> None:
        self._stop_lote_poll()
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                # after id já inválido após destroy/cancel
                pass
            self._resize_after_id = None
        self.unbind("<Configure>")
        self._lote_panel = None
        self._secoes_host = None
        self._body = None
        win = self._historico_win
        if win is not None and win.is_open:
            try:
                win.destroy()
            except Exception:
                # janela já fechada pelo SO
                pass
        self._historico_win = None
        rel = self._relatorio_win
        if rel is not None and rel.is_open:
            try:
                rel.destroy()
            except Exception:
                # janela já fechada pelo SO
                pass
        self._relatorio_win = None
        for child in self.winfo_children():
            child.destroy()

    def _on_splash_configure(self, event) -> None:
        if not self._splash_mode or event.widget is not self:
            return
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(80, self._splash_apply_layout)

    def _splash_apply_layout(self) -> None:
        self._resize_after_id = None
        if not self._splash_mode:
            return
        win_w = max(self.winfo_width(), 1)
        win_h = max(self.winfo_height(), 1)
        # Ignora tamanho pré-mapeamento (1x1) que deixava o fundo “branco”
        if win_w >= 200 and win_h >= 200:
            self._resize_splash_bg(win_w, win_h)
        if self._splash_btn is not None:
            compact = win_h < 500
            self._splash_btn.configure(
                width=200 if compact else 260,
                height=40 if compact else 48,
            )
            self._splash_btn.place(
                relx=0.5, rely=float(SPLASH_META["btn_rely"]), anchor="center"
            )
        if self._splash_version is not None:
            self._splash_version.place(relx=0.02, rely=0.97, anchor="sw")
        self._lift_splash_controls()

    def _resize_splash_bg(self, win_w: int, win_h: int) -> None:
        if self._splash_pil is None or self._splash_bg_label is None:
            return
        size = (max(win_w, 1), max(win_h, 1))
        if size == self._last_bg_size:
            return
        self._last_bg_size = size
        filled = _pil_fill(
            self._splash_pil, size[0], size[1], fill=SPLASH_META["window_bg"]
        )
        self._splash_bg_image = ctk.CTkImage(
            light_image=filled,
            dark_image=filled,
            size=size,
        )
        self._splash_bg_label.configure(image=self._splash_bg_image, text="")
        self._splash_bg_label.place(x=0, y=0, relwidth=1, relheight=1)

    def _show_splash(self) -> None:
        """Splash full-bleed com arte welcome + CTA e badge reais."""
        self._clear_root()
        self._splash_mode = True
        self._splash_bg_label = None
        self._splash_bg_image = None
        self._splash_btn = None
        self._splash_version = None
        self._last_bg_size = (0, 0)
        self.geometry("1024x576")
        self.minsize(1024, 576)
        self.maxsize(1024, 576)
        self.resizable(False, False)
        self.configure(fg_color=SPLASH_META["window_bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Frame “oco”: sem cor própria — a arte CTkLabel é o fundo
        frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        self._load_splash_background(frame)
        self._build_splash_controls(frame)

        self.bind("<Configure>", self._on_splash_configure)
        self.after(50, self._splash_apply_layout)
        self.after(200, self._splash_apply_layout)

    def _load_splash_background(self, frame: ctk.CTkFrame) -> None:
        bg_path = _splash_bg_path()
        self._last_bg_size = (0, 0)
        if bg_path is not None and bg_path.is_file():
            self._splash_pil = Image.open(bg_path).convert("RGB")
            # Janela splash fixa 1024x576
            win_w = max(self.winfo_width(), 1)
            win_h = max(self.winfo_height(), 1)
            if win_w < 200 or win_h < 200:
                win_w, win_h = 1024, 576
            filled = _pil_fill(
                self._splash_pil, win_w, win_h, fill=SPLASH_META["window_bg"]
            )
            self._splash_bg_image = ctk.CTkImage(
                light_image=filled,
                dark_image=filled,
                size=(win_w, win_h),
            )
            self._splash_bg_label = ctk.CTkLabel(
                frame,
                text="",
                image=self._splash_bg_image,
                fg_color=SPLASH_META["window_bg"],
                corner_radius=0,
            )
            # place absoluto atrás dos controles (sem lower — CTk canvas quebra stacking)
            self._splash_bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self._splash_pil = None
            self._splash_bg_label = ctk.CTkLabel(
                frame,
                text=f"{APP_NAME}\n{APP_TAGLINE}",
                font=ctk.CTkFont(size=28, weight="bold"),
                text_color=BRAND_FG,
                fg_color=SPLASH_META["window_bg"],
                corner_radius=0,
            )
            self._splash_bg_label.place(relx=0.5, rely=0.4, anchor="center")

    def _build_splash_controls(self, frame: ctk.CTkFrame) -> None:
        # Criados DEPOIS do fundo → ficam acima no stacking do CTk
        self._splash_btn = ctk.CTkButton(
            frame,
            text="Acessar sistema",
            width=260,
            height=48,
            corner_radius=24,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=SPLASH_META["btn_fg"],
            hover_color=SPLASH_META["btn_hover"],
            text_color=SPLASH_META["btn_text"],
            command=self._on_comecar,
        )
        self._splash_btn.place(
            relx=0.5, rely=float(SPLASH_META["btn_rely"]), anchor="center"
        )

        self._splash_version = ctk.CTkLabel(
            frame,
            text=f"Versão {APP_VERSION}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=SPLASH_META["badge_text"],
            fg_color=SPLASH_META["badge_fg"],
            corner_radius=6,
            height=26,
            width=110,
        )
        self._splash_version.place(relx=0.02, rely=0.97, anchor="sw")

    def _lift_splash_controls(self) -> None:
        if self._splash_btn is not None:
            self._splash_btn.lift()
        if self._splash_version is not None:
            self._splash_version.lift()

    def _on_comecar(self) -> None:
        self._try_enter_after_license()

    def _try_enter_after_license(self) -> None:
        """Splash/gate → main se licença ok; senão abre tela de ativação."""
        path = self._resolve_config_path()
        if not path.is_file():
            # Sem config: deixa entrar para configurar (server_url vazio = skip).
            self._show_main()
            return
        try:
            cfg = load_config(path)
        except ConfigError as exc:
            messagebox.showerror("Config", str(exc))
            return
        if not license_enabled(cfg):
            self._show_main()
            return
        try:
            result = ensure_license(cfg, app_version=APP_VERSION)
            if result.source == "cache":
                messagebox.showwarning(
                    "Licença",
                    "Servidor de licença inacessível.\n"
                    "Usando autorização em cache (período de graça).",
                )
            self._show_main()
        except LicenseError as exc:
            self._show_license_gate(erro=str(exc))

    def _prepare_post_splash_window(self, *, title: str, geometry: str) -> None:
        self._splash_mode = False
        self._clear_root()
        screen_w = max(self.winfo_screenwidth(), 1280)
        screen_h = max(self.winfo_screenheight(), 900)
        self.maxsize(screen_w, screen_h)
        self.minsize(480, 360)
        self.resizable(True, True)
        self.geometry(geometry)
        self.configure(fg_color=theme.BG)
        self.title(title)
        self.unbind("<Configure>")

    def _show_license_gate(self, *, erro: str = "") -> None:
        """Tela entre splash e main: colar chave e validar."""
        self._prepare_post_splash_window(
            title=f"{APP_NAME} — Ativar licença",
            geometry="520x360",
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = theme.make_card(self)
        card.grid(row=0, column=0, sticky="nsew", padx=24, pady=24)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=APP_NAME,
            font=theme.font_title(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=theme.PAD_CARD, pady=(theme.PAD_CARD, 4))
        ctk.CTkLabel(
            card,
            text="Ative a licença para acessar o sistema.",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=theme.PAD_CARD, pady=(0, 16))

        theme.style_field_label(card, "Chave de licença").grid(
            row=2, column=0, sticky="w", padx=theme.PAD_CARD, pady=(0, 2)
        )
        entry = theme.style_entry(card, uppercase=False, show="*")
        entry.grid(row=3, column=0, sticky="ew", padx=theme.PAD_CARD, pady=(0, 8))
        self._license_gate_entry = entry

        self._license_gate_erro = ctk.CTkLabel(
            card,
            text=erro or "",
            text_color=theme.WARNING,
            font=theme.font_subtitle(),
            wraplength=420,
            justify="left",
            anchor="w",
        )
        self._license_gate_erro.grid(
            row=4, column=0, sticky="ew", padx=theme.PAD_CARD, pady=(0, 12)
        )

        theme.btn_primary(
            card,
            "Validar e entrar",
            command=self._on_license_gate_validate,
            width=200,
        ).grid(row=5, column=0, sticky="w", padx=theme.PAD_CARD, pady=(0, theme.PAD_CARD))

        entry.focus_set()

    def _on_license_gate_validate(self) -> None:
        path = self._resolve_config_path()
        entry = getattr(self, "_license_gate_entry", None)
        key = entry.get().strip() if entry is not None else ""
        try:
            save_license_key(path, key)
            cfg = load_config(path)
            result = ensure_license(cfg, app_version=APP_VERSION)
        except (ConfigIoError, ConfigError, LicenseError) as exc:
            if getattr(self, "_license_gate_erro", None) is not None:
                self._license_gate_erro.configure(text=str(exc))
            else:
                messagebox.showerror("Licença", str(exc))
            return
        if result.source == "cache":
            messagebox.showwarning(
                "Licença",
                "Servidor de licença inacessível.\n"
                "Usando autorização em cache (período de graça).",
            )
        self._show_main()

    def _show_main(self) -> None:
        self._prepare_post_splash_window(
            title=f"{APP_NAME} — Automação APAC",
            geometry="980x780",
        )
        self.minsize(720, 520)
        self._build()
        self._load_into_form()
        if not self._main_ready:
            self.after(120, self._drain_log_queue)
            self._main_ready = True

    def _section_card(
        self,
        parent: ctk.CTkFrame,
        row: int,
        title: str,
        *,
        pady: tuple[int, int] = (0, 10),
        title_pady: tuple[int, int] | None = None,
    ) -> tuple[ctk.CTkFrame, int]:
        """Card branco com título; retorna (inner, próxima linha interna)."""
        card = theme.make_card(parent)
        card.grid(row=row, column=0, sticky="ew", padx=12, pady=pady)
        card.grid_columnconfigure(0, weight=1)
        top_pad, bottom_pad = (
            title_pady if title_pady is not None else (theme.PAD_CARD, 8)
        )
        ctk.CTkLabel(
            card,
            text=title,
            font=theme.font_section(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=theme.PAD_CARD,
            pady=(top_pad, bottom_pad),
        )
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=theme.PAD_CARD,
            pady=(0, theme.PAD_CARD),
        )
        inner.grid_columnconfigure(0, weight=1)
        return inner, 0

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        # A splash deixa a row 0 com weight=1 na raiz; sem zerar, o header ganha
        # espaço extra e abre um vão entre ele e o corpo.
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        header = ctk.CTkFrame(
            self,
            fg_color=theme.SURFACE,
            corner_radius=0,
            border_width=0,
        )
        header.grid(row=0, column=0, sticky="new")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=0)
        accent_bar = ctk.CTkFrame(header, fg_color=theme.BRAND_ACCENT, height=3)
        accent_bar.grid_propagate(False)
        accent_bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 4))
        title_wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            title_wrap,
            text=APP_NAME,
            font=theme.font_title(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_wrap,
            text="Configuração do lote · Automação APAC",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        mod_wrap = ctk.CTkFrame(header, fg_color="transparent")
        mod_wrap.grid(row=1, column=1, sticky="e", padx=(0, 10), pady=(8, 4))
        theme.style_field_label(mod_wrap, "Modelo de APAC").grid(
            row=0, column=0, sticky="w", padx=0, pady=(0, 2)
        )
        self.opt_modalidade = theme.style_option(
            mod_wrap,
            values=list(MODALIDADES_UI),
            width=160,
            command=self._on_modalidade_changed,
        )
        self.opt_modalidade.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self.opt_modalidade.set(modalidade_ui_label(self._modalidade))

        theme.btn_secondary(
            header,
            "Recarregar",
            command=self._load_into_form,
            width=110,
        ).grid(row=1, column=2, padx=(0, 16), pady=(8, 4))

        body = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.BG,
            corner_radius=0,
            border_width=0,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        body.grid_columnconfigure(0, weight=1)
        self._body = body

        card_clinica, r = self._section_card(
            body,
            0,
            "Clínica / planilha",
            pady=(10, 8),
            title_pady=(8, 6),
        )
        r = self._add_sistema_clinica_planilha_row(card_clinica, r)
        self._add_fields_grid(card_clinica, r, ("paciente_inicio",))

        self._secoes_host = ctk.CTkFrame(body, fg_color="transparent")
        self._secoes_host.grid(row=1, column=0, sticky="ew")
        self._secoes_host.grid_columnconfigure(0, weight=1)
        self._rebuild_dados_fixos_sections()

        self.lbl_aviso = ctk.CTkLabel(
            body,
            text="",
            text_color=theme.WARNING,
            font=theme.font_subtitle(),
            wraplength=720,
            justify="left",
            anchor="w",
        )
        self.lbl_aviso.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))

        actions = theme.make_card(body)
        actions.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        actions.grid_columnconfigure(0, weight=1)
        inner_actions = ctk.CTkFrame(actions, fg_color="transparent")
        inner_actions.grid(
            row=0, column=0, sticky="ew", padx=theme.PAD_CARD, pady=theme.PAD_CARD
        )
        inner_actions.grid_columnconfigure(0, weight=2)
        inner_actions.grid_columnconfigure(1, weight=1)
        inner_actions.grid_columnconfigure(2, weight=1)
        inner_actions.grid_columnconfigure(3, weight=1)

        self.btn_open_apac = theme.btn_primary(
            inner_actions,
            "Iniciar",
            command=lambda: self._run_cli("gerar-set"),
        )
        self.btn_open_apac.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="ew")
        self.btn_cancel = theme.btn_danger(
            inner_actions,
            "Cancelar",
            command=self._cancel_job,
            state="disabled",
        )
        self.btn_cancel.grid(row=0, column=1, padx=6, pady=0, sticky="ew")
        self.btn_export_set = theme.btn_secondary(
            inner_actions, "Exportar arquivo", command=self._export_set
        )
        self.btn_export_set.grid(row=0, column=2, padx=6, pady=0, sticky="ew")
        self.btn_preview_set = theme.btn_secondary(
            inner_actions, "Ver arquivo parcial", command=self._show_set_preview
        )
        self.btn_preview_set.grid(row=0, column=3, padx=(0, 0), pady=0, sticky="ew")
        self.btn_completar_erros = theme.btn_secondary(
            inner_actions,
            "Enviar pacientes pendentes",
            command=self._run_completar_erros,
            state="disabled",
        )
        self.btn_completar_erros.grid(
            row=1,
            column=0,
            columnspan=4,
            padx=0,
            pady=(6, 0),
            sticky="ew",
        )
        self._last_lote_snap: Optional[LoteSnapshot] = None
        self._sync_action_buttons_for_modalidade()

        # Fora do body scrollável — evita CTkScrollableFrame aninhado (ghosting no Windows).
        self._lote_panel = LotePanel(
            self,
            on_ver_historico=self._show_historico,
            on_ver_relatorio=self._show_relatorio,
        )
        self._lote_panel.grid(
            row=2, column=0, sticky="ew", padx=12, pady=(8, 12)
        )

    def _on_modalidade_changed(self, choice: str) -> None:
        nova = normalizar_modalidade(choice)
        if nova == self._modalidade:
            return
        self._modalidade = nova
        self._rebuild_planilha_anexos()
        self._rebuild_dados_fixos_sections()
        try:
            save_modalidade(self._resolve_config_path(), nova)
            self._append_log(
                f"[UI] Modalidade: {modalidade_ui_label(nova)}\n"
            )
        except ConfigIoError as exc:
            self._append_log(f"[UI] Não foi possível salvar modalidade: {exc}\n")

    def _cache_dados_fixos_from_entries(self) -> None:
        for key in DADOS_FIXOS_UI_KEYS:
            entry = self._entries.get(key)
            if entry is None:
                continue
            try:
                self._dados_fixos_cache[key] = entry.get().strip()
            except Exception:
                # widget já destruído no rebuild
                pass

    def _clear_dados_fixos_widgets(self) -> None:
        for key in DADOS_FIXOS_UI_KEYS:
            self._entries.pop(key, None)

    def _apply_dados_fixos_cache(self) -> None:
        for key, valor in self._dados_fixos_cache.items():
            entry = self._entries.get(key)
            if entry is None:
                continue
            entry.delete(0, "end")
            entry.insert(0, valor)

    def _rebuild_dados_fixos_sections(
        self, *, seed: Optional[dict[str, str]] = None
    ) -> None:
        host = self._secoes_host
        if host is None:
            return
        if seed is not None:
            self._dados_fixos_cache.update(seed)
        else:
            self._cache_dados_fixos_from_entries()

        for child in host.winfo_children():
            child.destroy()
        self._clear_dados_fixos_widgets()

        row = 0
        for titulo, keys in secoes_para_modalidade(self._modalidade):
            card, r = self._section_card(host, row, titulo)
            row += 1
            r = self._add_fields_grid(card, r, keys, cols=3)
            if titulo == "Solicitação / Autorização":
                self._add_solicitacao_autorizador_orgao_row(card, r)
        self._apply_dados_fixos_cache()
        clinica = getattr(self, "opt_clinica", None)
        if clinica is not None:
            self._apply_cnes_for_clinica(clinica.get())

        self._sync_action_buttons_for_modalidade()

    def _sync_action_buttons_for_modalidade(self) -> None:
        if self._job_running:
            return
        btn_iniciar = getattr(self, "btn_open_apac", None)
        btn_export = getattr(self, "btn_export_set", None)
        btn_preview = getattr(self, "btn_preview_set", None)
        btn_completar = getattr(self, "btn_completar_erros", None)
        if btn_iniciar is None or btn_export is None:
            return
        btn_iniciar.configure(state="normal")
        btn_export.configure(state="normal")
        if btn_preview is not None:
            btn_preview.configure(state="normal")
        if btn_completar is not None:
            pode, _ = self._pode_reenviar_falhas()
            btn_completar.configure(state="normal" if pode else "disabled")
        self._sync_relatorio_reenviar_btn()

    def _pode_reenviar_falhas(self) -> tuple[bool, str]:
        if self._job_running:
            return False, "Aguarde o comando em execução terminar."
        snap = self._last_lote_snap
        if snap is None or not tem_falhas_completar(snap.rows):
            return (
                False,
                "Não há pacientes em Erro ou Em revisão.\n"
                "Corrija os dados no BIODATA e use «Enviar pacientes pendentes» "
                "depois do «Iniciar».",
            )
        staging = self._staging_path_for_preview()
        if staging is None or not staging.is_file():
            return (
                False,
                "Nenhum arquivo parcial (lote_atual.SET).\n"
                "Execute «Iniciar» antes.",
            )
        return True, ""

    def _sync_relatorio_reenviar_btn(self) -> None:
        win = self._relatorio_win
        if win is None or not win.is_open:
            return
        pode, _ = self._pode_reenviar_falhas()
        win.set_enviar_pendentes_enabled(pode)

    def _run_reenviar_pacientes_pendentes(self, *, parent: Any = None) -> None:
        dlg_parent = parent if parent is not None else self
        pode, motivo = self._pode_reenviar_falhas()
        if not pode:
            if "Erro ou Em revisão" in motivo:
                messagebox.showinfo(
                    "Enviar pacientes pendentes", motivo, parent=dlg_parent
                )
            elif "lote_atual" in motivo:
                messagebox.showwarning(
                    "Enviar pacientes pendentes", motivo, parent=dlg_parent
                )
            else:
                messagebox.showinfo(
                    "Enviar pacientes pendentes", motivo, parent=dlg_parent
                )
            return
        snap = self._last_lote_snap
        n = contagem_falhas_completar(snap.rows) if snap is not None else 0
        if not messagebox.askyesno(
            "Enviar pacientes pendentes",
            f"Reconsultar o BIODATA e gravar no mesmo arquivo SET para "
            f"{n} paciente(s) em Erro ou Em revisão?\n\n"
            "Concluídos não serão processados de novo.",
            parent=dlg_parent,
        ):
            return
        self._append_log("[UI] Reenvio de pendentes iniciado.\n")
        self._reenvio_pendentes_em_execucao = True
        rel = self._relatorio_win
        if rel is not None and rel.is_open:
            rel.set_acoes_busy(True)
        self._run_cli("gerar-set", extra_args=["--somente-falhas"])

    def _run_reenviar_from_relatorio(self) -> None:
        win = self._relatorio_win
        parent = win if win is not None and win.is_open else self
        self._run_reenviar_pacientes_pendentes(parent=parent)

    def _run_completar_erros(self) -> None:
        self._run_reenviar_pacientes_pendentes()

    def _add_fields_grid(
        self,
        parent: ctk.CTkFrame,
        row: int,
        keys: tuple[str, ...],
        cols: int = 3,
    ) -> int:
        """Grade de campos (label em cima); chunks de `cols` por linha."""
        labels = {
            **DADOS_FIXOS_LABELS,
            "paciente_inicio": "Paciente início (lote)",
        }
        for start in range(0, len(keys), cols):
            chunk = keys[start : start + cols]
            wrap = ctk.CTkFrame(parent, fg_color="transparent")
            wrap.grid(row=row, column=0, sticky="ew", padx=0, pady=4)
            for i in range(cols):
                wrap.grid_columnconfigure(i, weight=1)
            for col, key in enumerate(chunk):
                cell = ctk.CTkFrame(wrap, fg_color="transparent")
                cell.grid(row=0, column=col, sticky="ew", padx=(0, 8), pady=0)
                cell.grid_columnconfigure(0, weight=1)
                theme.style_field_label(cell, labels.get(key, key)).grid(
                    row=0, column=0, sticky="w", padx=0, pady=(0, 2)
                )
                entry = theme.style_entry(cell)
                entry.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
                self._entries[key] = entry
            row += 1
        return row

    def _add_solicitacao_autorizador_orgao_row(
        self, parent: ctk.CTkFrame, row: int
    ) -> int:
        """CNS autorizador | Nome (órgão/código fixos por modalidade, fora da UI)."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=0, sticky="ew", padx=0, pady=4)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=1)

        col_cns = ctk.CTkFrame(wrap, fg_color="transparent")
        col_cns.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=0)
        theme.style_field_label(
            col_cns, DADOS_FIXOS_LABELS["autorizador_cns"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        entry_cns = theme.style_entry(col_cns, width=140)
        entry_cns.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self._entries["autorizador_cns"] = entry_cns

        col_nome = ctk.CTkFrame(wrap, fg_color="transparent")
        col_nome.grid(row=0, column=1, sticky="ew", padx=0, pady=0)
        col_nome.grid_columnconfigure(0, weight=1)
        theme.style_field_label(
            col_nome, DADOS_FIXOS_LABELS["autorizador_nome"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        entry_nome = theme.style_entry(col_nome)
        entry_nome.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        self._entries["autorizador_nome"] = entry_nome
        return row + 1

    def _add_sistema_clinica_planilha_row(
        self, parent: ctk.CTkFrame, row: int
    ) -> int:
        """Sistema | Clínica | anexos de planilha (1 no Glaucoma, 2 no Padrão)."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=0, sticky="ew", padx=0, pady=4)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=0)
        wrap.grid_columnconfigure(2, weight=1)

        col_sistema = ctk.CTkFrame(wrap, fg_color="transparent")
        col_sistema.grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=0)
        theme.style_field_label(col_sistema, "Sistema").grid(
            row=0, column=0, sticky="w", padx=0, pady=(0, 2)
        )
        self.opt_sistema = theme.style_option(
            col_sistema,
            values=list(SISTEMAS_UI),
            command=self._on_sistema_changed,
            width=150,
        )
        self.opt_sistema.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self.opt_sistema.set("BIODATA")

        col_clinica = ctk.CTkFrame(wrap, fg_color="transparent")
        col_clinica.grid(row=0, column=1, sticky="nw", padx=(0, 10), pady=0)
        theme.style_field_label(col_clinica, "ID da clínica").grid(
            row=0, column=0, sticky="w", padx=0, pady=(0, 2)
        )
        self.opt_clinica = theme.style_option(
            col_clinica,
            values=["oftalmocentro91"],
            width=160,
            command=self._on_clinica_changed,
        )
        self.opt_clinica.grid(row=1, column=0, sticky="w", padx=0, pady=0)

        self._planilha_anexos_host = ctk.CTkFrame(wrap, fg_color="transparent")
        self._planilha_anexos_host.grid(row=0, column=2, sticky="ew", padx=0, pady=0)
        self._planilha_anexos_host.grid_columnconfigure(0, weight=1)
        self._planilha_caminho_cache = ""
        self._planilha_prontuarios_cache = ""
        self._planilha_aba_glaucoma_cache = ""
        self._rebuild_planilha_anexos()

        self._apply_clinicas_for_sistema("biodata")
        return row + 1

    def _cache_planilha_anexos_from_entries(self) -> None:
        entry = self._entries.get("planilha_caminho")
        if entry is not None:
            try:
                self._planilha_caminho_cache = entry.get().strip()
            except Exception:
                # widget destruído no rebuild
                pass
        entry_pront = self._entries.get("planilha_prontuarios_caminho")
        if entry_pront is not None:
            try:
                self._planilha_prontuarios_cache = entry_pront.get().strip()
            except Exception:
                # widget destruído no rebuild
                pass
        opt_aba = getattr(self, "opt_aba_glaucoma", None)
        if opt_aba is not None:
            try:
                valor = opt_aba.get().strip()
                if valor and valor not in {"—", ABA_GLAUCOMA_TODAS}:
                    self._planilha_aba_glaucoma_cache = valor
                else:
                    self._planilha_aba_glaucoma_cache = ""
            except Exception:
                # widget destruído no rebuild
                pass

    def _current_aba_glaucoma(self) -> str:
        opt = getattr(self, "opt_aba_glaucoma", None)
        if opt is not None:
            try:
                valor = opt.get().strip()
                if valor and valor not in {"—", ABA_GLAUCOMA_TODAS}:
                    return valor
                return ""
            except Exception:
                # option menu já destruído
                pass
        return getattr(self, "_planilha_aba_glaucoma_cache", "") or ""

    def _populate_abas_glaucoma(
        self, caminho: str, *, preferida: str = ""
    ) -> None:
        opt = getattr(self, "opt_aba_glaucoma", None)
        if opt is None:
            return
        path = Path(caminho) if caminho else None
        abas: list[str] = []
        if path is not None and path.is_file():
            try:
                abas = listar_abas_faturamento_glaucoma(path)
            except SheetError as exc:
                self._append_log(f"[UI] Abas glaucoma: {exc}\n")
                abas = []
        if not abas:
            opt.configure(values=["—"], state="disabled")
            opt.set("—")
            self._planilha_aba_glaucoma_cache = ""
            return
        valores = [ABA_GLAUCOMA_TODAS, *abas]
        opt.configure(values=valores, state="normal")
        escolhida = (preferida or self._planilha_aba_glaucoma_cache or "").strip()
        lower = {a.casefold(): a for a in abas}
        hit = lower.get(escolhida.casefold()) if escolhida else None
        # Default: todas as abas (Iniciar processa o xlsx inteiro).
        selecionada = hit or ABA_GLAUCOMA_TODAS
        opt.set(selecionada)
        self._planilha_aba_glaucoma_cache = hit or ""

    def _on_aba_glaucoma_changed(self, choice: str) -> None:
        valor = (choice or "").strip()
        if not valor or valor == "—":
            return
        todas = valor == ABA_GLAUCOMA_TODAS
        self._planilha_aba_glaucoma_cache = "" if todas else valor
        caminho = getattr(self, "_planilha_caminho_cache", "") or ""
        entry = self._entries.get("planilha_caminho")
        if entry is not None:
            try:
                caminho = entry.get().strip() or caminho
            except Exception:
                # entry destruído
                pass
        override = Path(caminho) if caminho else None
        self._refresh_lote_panel(
            planilha_override=override if override and override.is_file() else None,
            aba_glaucoma_override="" if todas else valor,
        )

    def _rebuild_planilha_anexos(self) -> None:
        host = getattr(self, "_planilha_anexos_host", None)
        if host is None:
            return
        self._cache_planilha_anexos_from_entries()
        for child in host.winfo_children():
            child.destroy()
        self._entries.pop("planilha_caminho", None)
        self._entries.pop("planilha_prontuarios_caminho", None)
        if hasattr(self, "opt_aba_glaucoma"):
            del self.opt_aba_glaucoma

        glaucoma = self._modalidade == MODALIDADE_GLAUCOMA
        if glaucoma:
            host.grid_columnconfigure(0, weight=1)
            host.grid_columnconfigure(1, weight=1)
            col_planilha = ctk.CTkFrame(host, fg_color="transparent")
            col_planilha.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=0)
            col_planilha.grid_columnconfigure(0, weight=1)
            theme.style_field_label(col_planilha, "Planilha glaucoma (.xlsx)").grid(
                row=0, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 2)
            )
            entry = theme.style_entry(col_planilha)
            entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=0)
            self._entries["planilha_caminho"] = entry
            theme.btn_secondary(
                col_planilha, "Browse…", width=90, command=self._browse_planilha
            ).grid(row=1, column=1, sticky="e", padx=0, pady=0)

            col_aba = ctk.CTkFrame(host, fg_color="transparent")
            col_aba.grid(row=0, column=1, sticky="ew", padx=0, pady=0)
            col_aba.grid_columnconfigure(0, weight=1)
            theme.style_field_label(col_aba, "Abas (todas no Iniciar)").grid(
                row=0, column=0, sticky="w", padx=0, pady=(0, 2)
            )
            self.opt_aba_glaucoma = theme.style_option(
                col_aba,
                values=["—"],
                width=260,
                command=self._on_aba_glaucoma_changed,
            )
            self.opt_aba_glaucoma.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
            self.opt_aba_glaucoma.set("—")
            self.opt_aba_glaucoma.configure(state="disabled")
        else:
            host.grid_columnconfigure(0, weight=1)
            host.grid_columnconfigure(1, weight=1)
            col_planilha = ctk.CTkFrame(host, fg_color="transparent")
            col_planilha.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=0)
            col_planilha.grid_columnconfigure(0, weight=1)
            theme.style_field_label(col_planilha, "Planilha (.xlsx)").grid(
                row=0, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 2)
            )
            entry = theme.style_entry(col_planilha)
            entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=0)
            self._entries["planilha_caminho"] = entry
            theme.btn_secondary(
                col_planilha, "Browse…", width=90, command=self._browse_planilha
            ).grid(row=1, column=1, sticky="e", padx=0, pady=0)

            col_pront = ctk.CTkFrame(host, fg_color="transparent")
            col_pront.grid(row=0, column=1, sticky="ew", padx=0, pady=0)
            col_pront.grid_columnconfigure(0, weight=1)
            theme.style_field_label(
                col_pront, "Planilha prontuários (.xlsx)"
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 2))
            entry_pront = theme.style_entry(col_pront)
            entry_pront.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=0)
            self._entries["planilha_prontuarios_caminho"] = entry_pront
            theme.btn_secondary(
                col_pront,
                "Browse…",
                width=90,
                command=self._browse_planilha_prontuarios,
            ).grid(row=1, column=1, sticky="e", padx=0, pady=0)

        caminho = getattr(self, "_planilha_caminho_cache", "") or ""
        if caminho:
            entry = self._entries["planilha_caminho"]
            entry.delete(0, "end")
            entry.insert(0, caminho)
        pront = getattr(self, "_planilha_prontuarios_cache", "") or ""
        entry_pront = self._entries.get("planilha_prontuarios_caminho")
        if entry_pront is not None and pront:
            entry_pront.delete(0, "end")
            entry_pront.insert(0, pront)
        if glaucoma:
            self._populate_abas_glaucoma(
                caminho,
                preferida=getattr(self, "_planilha_aba_glaucoma_cache", "") or "",
            )

    def _apply_clinicas_for_sistema(self, sistema: str) -> None:
        key = normalizar_sistema_origem(sistema)
        clinicas = list(CLINICAS_POR_SISTEMA.get(key) or ())
        if not clinicas:
            self.opt_clinica.configure(values=["—"], state="disabled")
            self.opt_clinica.set("—")
            self._apply_cnes_for_clinica("")
            return
        self.opt_clinica.configure(values=clinicas, state="normal")
        if key == "biodata" or len(clinicas) == 1:
            self.opt_clinica.set(clinicas[0])
            self.opt_clinica.configure(state="disabled")
        else:
            atual = self.opt_clinica.get()
            self.opt_clinica.set(atual if atual in clinicas else clinicas[0])
        self._apply_cnes_for_clinica(self.opt_clinica.get())

    def _apply_cnes_for_clinica(self, clinica_id: str) -> None:
        cid = "" if clinica_id.strip() == "—" else clinica_id
        defaults = aplicar_defaults_clinica(cid)
        if not defaults:
            return
        for key in CNES_UI_KEYS:
            entry = self._entries.get(key)
            if entry is None or key not in defaults:
                continue
            entry.delete(0, "end")
            entry.insert(0, defaults[key])

    def _on_sistema_changed(self, choice: str) -> None:
        self._apply_clinicas_for_sistema(choice)

    def _on_clinica_changed(self, choice: str) -> None:
        self._apply_cnes_for_clinica(choice)

    def _append_log(self, text: str) -> None:
        self._log_buffer.append(text)
        win = self._historico_win
        if win is not None and win.is_open:
            win.append_text(text)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(120, self._drain_log_queue)

    def _show_historico(self) -> None:
        win = self._historico_win
        if win is not None and win.is_open:
            win.set_text("".join(self._log_buffer))
            win.present()
            return
        win = HistoricoLogWindow(self, title=f"{APP_NAME} — Histórico")
        win.set_text("".join(self._log_buffer))
        self._historico_win = win
        win.present()

    def _show_relatorio(self) -> None:
        snap = load_lote_snapshot(self._resolve_config_path())
        self._last_lote_snap = snap
        win = self._relatorio_win
        if win is not None and win.is_open:
            win.apply_rows(snap.rows)
            self._sync_relatorio_reenviar_btn()
            win.present()
            return
        win = RelatorioLoteWindow(
            self,
            title=f"{APP_NAME} — Relatório do lote",
            on_export_cliente=self._export_relatorio_cliente,
            on_enviar_pendentes=self._run_reenviar_from_relatorio,
        )
        win.apply_rows(snap.rows)
        self._relatorio_win = win
        self._sync_relatorio_reenviar_btn()
        win.present()

    def _export_relatorio_cliente(self) -> None:
        """Gera relatório de cliente (PDF/xlsx/csv) a partir do SET staging + falhas.

        Não pede arquivo SET: usa lote_atual.SET interno. I/O pesado roda em
        thread para não travar a UI (planilha glaucoma).
        """
        from apac_bot.relatorio_apac import (
            RelatorioApac,
            carregar_fila_e_progresso,
            export_relatorio_csv,
            export_relatorio_pdf,
            export_relatorio_xlsx,
            montar_relatorio_de_arquivos,
            nome_arquivo_relatorio_cliente,
        )
        from apac_bot.set_layout import SetLayoutError
        from apac_bot.set_pipeline import caminho_staging

        if self._export_cliente_busy:
            return

        parent = self._relatorio_win if (
            self._relatorio_win is not None and self._relatorio_win.is_open
        ) else self

        try:
            cfg = load_config(self._resolve_config_path())
        except (ConfigError, OSError) as exc:
            messagebox.showerror("Exportar para cliente", str(exc), parent=parent)
            return

        staging = caminho_staging(cfg)
        if not staging.is_file():
            messagebox.showwarning(
                "Exportar para cliente",
                "Nenhum lote SET gerado ainda.\n"
                "Execute «Iniciar» antes de exportar o relatório.",
                parent=parent,
            )
            return

        planilha = self._ui_planilha_path()
        if planilha is not None:
            cfg = cfg.with_planilha(planilha)

        self._export_cliente_busy = True
        if self._relatorio_win is not None and self._relatorio_win.is_open:
            self._relatorio_win.set_export_cliente_busy(True)
        self._append_log("[UI] Gerando relatório para cliente…\n")

        def _finish_busy() -> None:
            self._export_cliente_busy = False
            if self._relatorio_win is not None and self._relatorio_win.is_open:
                self._relatorio_win.set_export_cliente_busy(False)

        def _on_montar_ok(relatorio: RelatorioApac) -> None:
            dest_parent = self._relatorio_win if (
                self._relatorio_win is not None and self._relatorio_win.is_open
            ) else self
            destino = filedialog.asksaveasfilename(
                parent=dest_parent,
                title="Salvar relatório para cliente",
                defaultextension=".pdf",
                initialfile=nome_arquivo_relatorio_cliente(relatorio),
                filetypes=[
                    ("PDF", "*.pdf"),
                    ("Excel", "*.xlsx"),
                    ("CSV", "*.csv"),
                    ("Todos", "*.*"),
                ],
            )
            if not destino:
                _finish_busy()
                return
            dest = Path(destino)
            suffix = dest.suffix.lower()
            if suffix not in {".pdf", ".xlsx", ".csv"}:
                dest = dest.with_suffix(".pdf")
                suffix = ".pdf"

            def write_worker() -> None:
                try:
                    if suffix == ".csv":
                        export_relatorio_csv(dest, relatorio)
                    elif suffix == ".xlsx":
                        export_relatorio_xlsx(dest, relatorio)
                    else:
                        export_relatorio_pdf(dest, relatorio)
                except (OSError, ModuleNotFoundError) as exc:
                    err_msg = f"Falha ao salvar:\n{exc}"

                    def _fail(msg: str = err_msg) -> None:
                        _finish_busy()
                        messagebox.showerror(
                            "Exportar para cliente",
                            msg,
                            parent=dest_parent,
                        )

                    self.after(0, _fail)
                    return

                def _ok() -> None:
                    _finish_busy()
                    self._append_log(
                        f"[UI] Relatório cliente exportado: {dest}\n"
                    )
                    messagebox.showinfo(
                        "Exportar para cliente",
                        f"Arquivo salvo em:\n{dest}",
                        parent=dest_parent,
                    )

                self.after(0, _ok)

            threading.Thread(target=write_worker, daemon=True).start()

        def _on_montar_err(msg: str) -> None:
            _finish_busy()
            messagebox.showerror(
                "Exportar para cliente",
                msg,
                parent=parent,
            )

        def montar_worker() -> None:
            try:
                fila, progress, mapa_glauc = carregar_fila_e_progresso(
                    cfg, planilha_override=planilha
                )
                relatorio = montar_relatorio_de_arquivos(
                    cfg,
                    staging,
                    fila,
                    progress,
                    mapa_glaucoma=mapa_glauc,
                )
            except (SheetError, SetLayoutError, OSError, ConfigError) as exc:
                err = str(exc)
                self.after(0, lambda m=err: _on_montar_err(m))
                return
            except Exception as exc:  # noqa: BLE001 — UI worker
                err = f"Falha ao montar relatório:\n{exc}"
                self.after(0, lambda m=err: _on_montar_err(m))
                return
            self.after(0, lambda r=relatorio: _on_montar_ok(r))

        threading.Thread(target=montar_worker, daemon=True).start()

    @staticmethod
    def _normalizar_path_planilha(path: str) -> str:
        raw = path.strip()
        if not raw:
            return ""
        p = Path(raw)
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = raw
        if sys.platform == "win32":
            return resolved.casefold()
        return resolved

    def _planilha_path_texto_ui(self) -> str:
        entry = self._entries.get("planilha_caminho")
        texto = ""
        if entry is not None:
            try:
                texto = entry.get().strip()
            except Exception as exc:
                log.debug("[ui] leitura planilha_caminho: %s", exc)
                texto = ""
        if not texto:
            texto = getattr(self, "_planilha_caminho_cache", "") or ""
            texto = texto.strip()
        return texto

    def _cfg_para_reset_lote(self) -> AppConfig:
        cfg = load_config(self._resolve_config_path())
        texto = self._planilha_path_texto_ui()
        if texto:
            cfg = cfg.with_planilha(texto)
        return cfg

    def _reset_lote_operacional_se_necessario(self, *, nova_sessao: bool = False) -> None:
        if self._job_running:
            return
        path_efetivo = self._normalizar_path_planilha(self._planilha_path_texto_ui())
        deve = nova_sessao or (
            bool(path_efetivo) and path_efetivo != self._planilha_path_ultimo_reset
        )
        if not deve:
            return
        try:
            cfg = self._cfg_para_reset_lote()
            removed = reset_lote_operacional(cfg)
        except (ConfigError, OSError) as exc:
            log.warning("[lote-reset] falha ao reiniciar lote: %s", exc)
            self._append_log(f"[UI] Não foi possível reiniciar o lote: {exc}\n")
            return
        self._planilha_path_ultimo_reset = path_efetivo
        if removed > 0:
            self._append_log(
                f"[UI] Lote reiniciado — progresso anterior apagado ({removed} registro(s)).\n"
            )
        else:
            self._append_log("[UI] Lote reiniciado — painel sem progresso anterior.\n")

    def _ui_planilha_path(self) -> Optional[Path]:
        """Path da planilha no campo da UI; None se vazio ou arquivo inexistente."""
        entry = self._entries.get("planilha_caminho")
        texto = ""
        if entry is not None:
            try:
                texto = entry.get().strip()
            except Exception:
                # entry destruído no rebuild
                texto = ""
        if not texto:
            texto = getattr(self, "_planilha_caminho_cache", "") or ""
            texto = texto.strip()
        if not texto:
            return None
        path = Path(texto)
        if not path.is_file():
            return None
        return path

    def _refresh_lote_panel(
        self,
        *,
        planilha_override: Optional[Path] = None,
        aba_glaucoma_override: Optional[str] = None,
    ) -> Optional[LoteSnapshot]:
        panel = self._lote_panel
        if panel is None:
            return None
        override = planilha_override
        if override is None:
            override = self._ui_planilha_path()
        elif not override.is_file():
            override = None
        if override is None:
            snap = snapshot_sem_planilha()
            panel.apply_snapshot(snap)
            return snap
        aba = aba_glaucoma_override
        if aba is None and self._modalidade == MODALIDADE_GLAUCOMA:
            aba = self._current_aba_glaucoma() or None
        snap = load_lote_snapshot(
            self._resolve_config_path(),
            planilha_override=override,
            aba_glaucoma_override=aba,
        )
        panel.apply_snapshot(snap)
        self._last_lote_snap = snap
        rel = self._relatorio_win
        if rel is not None and rel.is_open:
            rel.apply_rows(snap.rows)
        if not self._job_running:
            self._sync_action_buttons_for_modalidade()
        else:
            self._sync_relatorio_reenviar_btn()
        return snap

    def _stop_lote_poll(self) -> None:
        if self._lote_poll_after_id is None:
            return
        try:
            self.after_cancel(self._lote_poll_after_id)
        except Exception:
            # after id já inválido após destroy/cancel
            pass
        self._lote_poll_after_id = None

    def _schedule_lote_poll(self) -> None:
        self._stop_lote_poll()
        self._lote_poll_after_id = self.after(500, self._poll_lote_tick)

    def _poll_lote_tick(self) -> None:
        self._lote_poll_after_id = None
        self._refresh_lote_panel()
        if self._job_running:
            self._lote_poll_after_id = self.after(500, self._poll_lote_tick)

    def _resolve_config_path(self) -> Path:
        return Path(self.config_path)

    def _collect_form(self) -> UiFormData:
        self._cache_dados_fixos_from_entries()
        dados = dict(self._dados_fixos_cache)
        for key in DADOS_FIXOS_UI_KEYS:
            if key in self._entries:
                dados[key] = self._entries[key].get().strip()
        sistema = normalizar_sistema_origem(self.opt_sistema.get())
        clinica = self.opt_clinica.get().strip()
        if clinica == "—":
            clinica = ""
        entry_planilha = self._entries.get("planilha_caminho")
        planilha = entry_planilha.get().strip() if entry_planilha is not None else ""
        entry_pront = self._entries.get("planilha_prontuarios_caminho")
        if entry_pront is not None:
            prontuarios = entry_pront.get().strip()
        else:
            prontuarios = getattr(self, "_planilha_prontuarios_cache", "") or ""
        return UiFormData(
            sistema_origem=sistema,
            clinica_id=clinica,
            planilha_caminho=planilha,
            planilha_prontuarios_caminho=prontuarios,
            planilha_aba_glaucoma=self._current_aba_glaucoma(),
            paciente_inicio=self._entries["paciente_inicio"].get().strip(),
            modalidade=self._modalidade,
            dados_fixos=dados,
        )

    def _fill_form(self, form: UiFormData) -> None:
        self._modalidade = normalizar_modalidade(form.modalidade)
        self.opt_modalidade.set(modalidade_ui_label(self._modalidade))
        self._planilha_caminho_cache = form.planilha_caminho
        self._planilha_prontuarios_cache = form.planilha_prontuarios_caminho
        self._planilha_aba_glaucoma_cache = form.planilha_aba_glaucoma
        self._rebuild_planilha_anexos()

        label = sistema_ui_label(form.sistema_origem)
        self.opt_sistema.set(label)
        self._apply_clinicas_for_sistema(form.sistema_origem)
        clinicas = CLINICAS_POR_SISTEMA.get(
            normalizar_sistema_origem(form.sistema_origem), ()
        )
        if form.clinica_id and form.clinica_id in clinicas:
            # Reabilita só para setar valor se estava disabled
            self.opt_clinica.configure(state="normal")
            self.opt_clinica.set(form.clinica_id)
            if (
                normalizar_sistema_origem(form.sistema_origem) == "biodata"
                or len(clinicas) == 1
            ):
                self.opt_clinica.configure(state="disabled")

        entry_pi = self._entries.get("paciente_inicio")
        if entry_pi is not None:
            entry_pi.delete(0, "end")
            entry_pi.insert(0, form.paciente_inicio)

        self._rebuild_dados_fixos_sections(seed=form.dados_fixos_completos())

    def _load_into_form(self) -> None:
        path = self._resolve_config_path()
        try:
            form = load_form(path)
        except ConfigIoError as exc:
            messagebox.showerror("Config", str(exc))
            self._append_log(f"[UI] Erro ao carregar: {exc}\n")
            return
        self._fill_form(form)
        if secrets_missing(path):
            self.lbl_aviso.configure(
                text=(
                    "Aviso: secrets.local.json ausente ou sem senha — "
                    "login BIODATA automático não funcionará até configurar."
                )
            )
        else:
            self.lbl_aviso.configure(text="")
        self._append_log(f"[UI] Config carregada: {path}\n")
        self._reset_lote_operacional_se_necessario(nova_sessao=True)
        self._refresh_lote_panel()

    def _browse_planilha(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecionar planilha",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
        )
        if not path:
            return
        entry = self._entries.get("planilha_caminho")
        if entry is None:
            self._planilha_caminho_cache = path
        else:
            entry.delete(0, "end")
            entry.insert(0, path)
            self._planilha_caminho_cache = path
        if self._modalidade == MODALIDADE_GLAUCOMA:
            self._populate_abas_glaucoma(
                path,
                preferida=self._planilha_aba_glaucoma_cache,
            )
        self._reset_lote_operacional_se_necessario(nova_sessao=False)
        self._refresh_lote_panel(
            planilha_override=Path(path),
            aba_glaucoma_override=(
                self._current_aba_glaucoma() or None
                if self._modalidade == MODALIDADE_GLAUCOMA
                else None
            ),
        )

    def _browse_planilha_prontuarios(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecionar planilha de prontuários",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
        )
        if not path:
            return
        entry = self._entries.get("planilha_prontuarios_caminho")
        if entry is None:
            self._planilha_prontuarios_cache = path
            return
        entry.delete(0, "end")
        entry.insert(0, path)
        self._planilha_prontuarios_cache = path

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.btn_cancel.configure(state="normal" if running else "disabled")
        if running:
            for btn in (
                self.btn_open_apac,
                self.btn_export_set,
                getattr(self, "btn_completar_erros", None),
            ):
                if btn is not None:
                    btn.configure(state="disabled")
            rel = self._relatorio_win
            if rel is not None and rel.is_open:
                rel.set_acoes_busy(True)
            self._refresh_lote_panel()
            self._schedule_lote_poll()
        else:
            self._sync_action_buttons_for_modalidade()
            self._stop_lote_poll()
            snap = self._refresh_lote_panel()
            rel = self._relatorio_win
            if rel is not None and rel.is_open:
                rel.set_acoes_busy(False)
                self._sync_relatorio_reenviar_btn()
            if self._reenvio_pendentes_em_execucao:
                self._append_log("[UI] Reenvio de pendentes concluído.\n")
                self._reenvio_pendentes_em_execucao = False
            if snap is not None and linhas_com_problema(snap.rows):
                self._show_relatorio()

    def _staging_path_for_preview(self) -> Optional[Path]:
        from apac_bot.config import load_config
        from apac_bot.set_pipeline import caminho_staging

        try:
            cfg = load_config(self._resolve_config_path())
        except Exception:
            return None
        return caminho_staging(cfg)

    def _show_set_preview(self) -> None:
        """Abre (ou foca) a janela opcional com o arquivo parcial do staging."""
        staging = self._staging_path_for_preview()
        if staging is None:
            messagebox.showerror(
                "Ver arquivo parcial",
                "Não foi possível resolver o caminho do staging "
                "(config inválida?).",
            )
            return
        win = self._set_preview_win
        if win is not None and win.is_open:
            win.set_staging_path(staging)
            win.present()
            return
        win = SetPreviewWindow(
            self,
            staging_path=staging,
            title=f"{APP_NAME} — Arquivo parcial",
        )
        self._set_preview_win = win
        win.present()

    def _export_set(self) -> None:
        """Copia o staging para o destino escolhido pelo usuario."""
        from apac_bot.config import load_config
        from apac_bot.set_layout import competencia_mes_anterior, nome_arquivo_set
        from apac_bot.set_pipeline import caminho_staging

        try:
            cfg = load_config(self._resolve_config_path())
        except Exception as exc:
            messagebox.showerror("Exportar arquivo", str(exc))
            return
        staging = caminho_staging(cfg)
        if not staging.is_file():
            messagebox.showwarning(
                "Exportar arquivo",
                "Nenhum arquivo gerado ainda.\n"
                "Execute «Iniciar» antes de exportar.",
            )
            return
        # Cabecalho INTERNO: "01" + "#APAC" + AAAAMM (pos 7..13)
        try:
            header = staging.read_bytes().split(b"\r\n", 1)[0].decode("latin-1")
            comp = header[7:13] if len(header) >= 13 and header[7:13].isdigit() else ""
        except OSError:
            comp = ""
        if not comp:
            comp = competencia_mes_anterior()
        default_name = nome_arquivo_set(comp, cfg.modalidade)
        ext = Path(default_name).suffix or ".SET"
        destino = filedialog.asksaveasfilename(
            title="Salvar arquivo",
            defaultextension=ext,
            initialfile=default_name,
            filetypes=[
                (f"Arquivo {ext.lstrip('.').upper()}", f"*{ext}"),
                ("Todos", "*.*"),
            ],
        )
        if not destino:
            return
        dest = Path(destino)
        if dest.suffix.upper() != ext.upper():
            dest = dest.with_suffix(ext)
        try:
            dest.write_bytes(staging.read_bytes())
        except OSError as exc:
            messagebox.showerror("Exportar arquivo", f"Falha ao salvar:\n{exc}")
            return
        self._append_log(f"[UI] Arquivo exportado: {dest}\n")
        messagebox.showinfo("Exportar arquivo", f"Arquivo salvo em:\n{dest}")

    def _cancel_job(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self._append_log("[UI] Cancelando processo…\n")
        try:
            proc.terminate()
        except OSError as exc:
            self._append_log(f"[UI] Falha ao cancelar: {exc}\n")

    def _run_cli(
        self,
        command: str,
        *,
        extra_args: Optional[list[str]] = None,
    ) -> None:
        if self._job_running:
            messagebox.showwarning("Aguarde", "Já existe um comando em execução.")
            return
        path = self._resolve_config_path()
        form = self._collect_form()
        erros = validate_form(form)
        if erros:
            messagebox.showerror(
                "Validação",
                "Corrija e salve antes de executar:\n" + "\n".join(erros),
            )
            return
        try:
            save_form(path, form)
        except ConfigIoError as exc:
            messagebox.showerror("Salvar", str(exc))
            return

        from apac_bot.runtime_paths import is_frozen

        extras = list(extra_args or [])
        if is_frozen():
            cmd = [sys.executable, command, "--config", str(path), *extras]
        else:
            cmd = [
                sys.executable,
                "-m",
                "apac_bot",
                command,
                "--config",
                str(path),
                *extras,
            ]
        self._append_log(f"[UI] > {' '.join(cmd)}\n")
        self._set_job_running(True)

        def worker() -> None:
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(path.parent.resolve()),
                )
                stdout = self._proc.stdout
                if stdout is None:
                    raise RuntimeError("subprocess sem stdout capturado")
                for line in stdout:
                    self._log_queue.put(line)
                code = self._proc.wait()
                self._log_queue.put(f"[UI] Processo finalizado (código {code}).\n")
            except Exception as exc:  # noqa: BLE001 — UI worker
                self._log_queue.put(f"[UI] Erro ao executar: {exc}\n")
            finally:
                self._proc = None
                self.after(0, lambda: self._set_job_running(False))

        threading.Thread(target=worker, daemon=True).start()


def run_ui(config_path: str | None = None) -> None:
    app = ApacBotApp(Path(config_path) if config_path else None)
    app.mainloop()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=f"UI desktop {APP_NAME}")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Caminho do config.json (padrão: config.json)",
    )
    args = parser.parse_args(argv)
    run_ui(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
