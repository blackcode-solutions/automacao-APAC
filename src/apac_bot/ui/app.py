"""Janela CustomTkinter — splash SIS DG + config dinâmica / ações do bot."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image

from apac_bot.ui.config_io import (
    CLINICAS_POR_SISTEMA,
    CNES_UI_KEYS,
    DADOS_FIXOS_LABELS,
    DADOS_FIXOS_UI_KEYS,
    ORGAO_EMISS_TIPOS,
    SISTEMAS_UI,
    UI_SECOES_TELA,
    ConfigIoError,
    UiFormData,
    aplicar_defaults_clinica,
    codigo_orgao_emiss,
    default_config_path,
    load_form,
    normalizar_sistema_origem,
    save_form,
    secrets_missing,
    sistema_ui_label,
    tipo_orgao_emiss,
    validate_form,
)
from apac_bot.ui import theme
from apac_bot.ui.lote_data import (
    LoteSnapshot,
    linhas_com_problema,
    load_lote_snapshot,
)
from apac_bot.ui.lote_panel import HistoricoLogWindow, LotePanel, RelatorioLoteWindow

# Marca / splash
APP_NAME = "SIS DG"
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


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _splash_bg_path() -> Optional[Path]:
    """Resolve PNG (preferido) ou JPG da splash welcome."""
    assets = _assets_dir()
    for name in SPLASH_META["files"]:
        path = assets / name
        if path.is_file():
            return path
    return None


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
        self._lote_panel: Optional[LotePanel] = None
        self._historico_win: Optional[HistoricoLogWindow] = None
        self._relatorio_win: Optional[RelatorioLoteWindow] = None
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

        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        # Splash fixa 1024x576 (proporção da arte welcome — evita logo achatada)
        self.geometry("1024x576")
        self.minsize(1024, 576)
        self.maxsize(1024, 576)
        self.resizable(False, False)
        self.configure(fg_color=SPLASH_BG)
        self._show_splash()

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
        self._show_main()

    def _show_main(self) -> None:
        self._splash_mode = False
        self._clear_root()
        # Libera o maxsize da splash (senão a janela continua travada).
        screen_w = max(self.winfo_screenwidth(), 1280)
        screen_h = max(self.winfo_screenheight(), 900)
        self.maxsize(screen_w, screen_h)
        self.minsize(720, 520)
        self.resizable(True, True)
        self.geometry("980x780")
        self.configure(fg_color=theme.BG)
        self.title(f"{APP_NAME} — Automação APAC")
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
        accent_bar = ctk.CTkFrame(header, fg_color=theme.BRAND_ACCENT, height=3)
        accent_bar.grid_propagate(False)
        accent_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
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
        theme.btn_secondary(
            header,
            "Recarregar",
            command=self._load_into_form,
            width=110,
        ).grid(row=1, column=1, padx=(0, 16), pady=(8, 4))

        body = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.BG,
            corner_radius=0,
            border_width=0,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        body.grid_columnconfigure(0, weight=1)

        row = 0
        card_clinica, r = self._section_card(
            body,
            row,
            "Clínica / planilha",
            pady=(10, 8),
            title_pady=(8, 6),
        )
        row += 1
        r = self._add_sistema_clinica_planilha_row(card_clinica, r)
        r = self._add_fields_grid(card_clinica, r, ("paciente_inicio",))

        for titulo, keys in UI_SECOES_TELA:
            card, r = self._section_card(body, row, titulo)
            row += 1
            n_cols = 5 if titulo == "Procedimentos" else 3
            r = self._add_fields_grid(card, r, keys, cols=n_cols)
            if titulo == "Solicitação / Autorização":
                r = self._add_solicitacao_autorizador_orgao_row(card, r)

        self._apply_cnes_for_clinica(self.opt_clinica.get())

        self.lbl_aviso = ctk.CTkLabel(
            body,
            text="",
            text_color=theme.WARNING,
            font=theme.font_subtitle(),
            wraplength=720,
            justify="left",
            anchor="w",
        )
        self.lbl_aviso.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 6))
        row += 1

        actions = theme.make_card(body)
        actions.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 10))
        actions.grid_columnconfigure(0, weight=1)
        inner_actions = ctk.CTkFrame(actions, fg_color="transparent")
        inner_actions.grid(
            row=0, column=0, sticky="ew", padx=theme.PAD_CARD, pady=theme.PAD_CARD
        )
        inner_actions.grid_columnconfigure(0, weight=2)
        inner_actions.grid_columnconfigure(1, weight=1)
        inner_actions.grid_columnconfigure(2, weight=1)

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
            inner_actions, "Exportar SET", command=self._export_set
        )
        self.btn_export_set.grid(row=0, column=2, padx=(6, 0), pady=0, sticky="ew")

        # Fora do body scrollável — evita CTkScrollableFrame aninhado (ghosting no Windows).
        self._lote_panel = LotePanel(
            self,
            on_ver_historico=self._show_historico,
            on_ver_relatorio=self._show_relatorio,
        )
        self._lote_panel.grid(
            row=2, column=0, sticky="ew", padx=12, pady=(8, 12)
        )

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
                if key == "tipo_apac":
                    self.opt_tipo_apac = theme.style_option(
                        cell, values=["1", "3"], width=80
                    )
                    self.opt_tipo_apac.grid(
                        row=1, column=0, sticky="w", padx=0, pady=0
                    )
                    self.opt_tipo_apac.set("3")
                else:
                    entry = theme.style_entry(cell)
                    entry.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
                    self._entries[key] = entry
            row += 1
        return row

    def _add_solicitacao_autorizador_orgao_row(
        self, parent: ctk.CTkFrame, row: int
    ) -> int:
        """CNS autorizador | Nome | Órgão emissor | Código emissor (readonly)."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=0, sticky="ew", padx=0, pady=4)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_columnconfigure(2, weight=0)
        wrap.grid_columnconfigure(3, weight=0)

        col_cns = ctk.CTkFrame(wrap, fg_color="transparent")
        col_cns.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=0)
        theme.style_field_label(
            col_cns, DADOS_FIXOS_LABELS["autorizador_cns"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        entry_cns = theme.style_entry(col_cns, width=140)
        entry_cns.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self._entries["autorizador_cns"] = entry_cns

        col_nome = ctk.CTkFrame(wrap, fg_color="transparent")
        col_nome.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=0)
        col_nome.grid_columnconfigure(0, weight=1)
        theme.style_field_label(
            col_nome, DADOS_FIXOS_LABELS["autorizador_nome"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        entry_nome = theme.style_entry(col_nome)
        entry_nome.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        self._entries["autorizador_nome"] = entry_nome

        col_tipo = ctk.CTkFrame(wrap, fg_color="transparent")
        col_tipo.grid(row=0, column=2, sticky="nw", padx=(0, 8), pady=0)
        theme.style_field_label(
            col_tipo, DADOS_FIXOS_LABELS["orgao_emiss_tipo"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        self.opt_orgao_emiss = theme.style_option(
            col_tipo,
            values=list(ORGAO_EMISS_TIPOS),
            width=120,
            command=self._on_orgao_emiss_changed,
        )
        self.opt_orgao_emiss.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self.opt_orgao_emiss.set("Municipal")

        col_cod = ctk.CTkFrame(wrap, fg_color="transparent")
        col_cod.grid(row=0, column=3, sticky="nw", padx=0, pady=0)
        theme.style_field_label(
            col_cod, DADOS_FIXOS_LABELS["cod_orgao_emiss"]
        ).grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))
        entry_cod = theme.style_entry(col_cod, width=120)
        entry_cod.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self._entries["cod_orgao_emiss"] = entry_cod
        self._sync_orgao_emiss_codigo("Municipal")
        return row + 1

    def _sync_orgao_emiss_codigo(self, tipo: str) -> None:
        entry = self._entries.get("cod_orgao_emiss")
        if entry is None:
            return
        codigo = codigo_orgao_emiss(tipo)
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, codigo)
        entry.configure(state="disabled")

    def _on_orgao_emiss_changed(self, choice: str) -> None:
        self._sync_orgao_emiss_codigo(choice)

    def _add_sistema_clinica_planilha_row(
        self, parent: ctk.CTkFrame, row: int
    ) -> int:
        """Sistema | Clínica | Planilha | Planilha prontuários."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=0, sticky="ew", padx=0, pady=4)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=0)
        wrap.grid_columnconfigure(2, weight=1)
        wrap.grid_columnconfigure(3, weight=1)

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

        col_planilha = ctk.CTkFrame(wrap, fg_color="transparent")
        col_planilha.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=0)
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

        col_pront = ctk.CTkFrame(wrap, fg_color="transparent")
        col_pront.grid(row=0, column=3, sticky="ew", padx=0, pady=0)
        col_pront.grid_columnconfigure(0, weight=1)
        theme.style_field_label(col_pront, "Planilha prontuários (.xlsx)").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 2)
        )
        entry_pront = theme.style_entry(col_pront)
        entry_pront.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=0)
        self._entries["planilha_prontuarios_caminho"] = entry_pront
        theme.btn_secondary(
            col_pront,
            "Browse…",
            width=90,
            command=self._browse_planilha_prontuarios,
        ).grid(row=1, column=1, sticky="e", padx=0, pady=0)

        self._apply_clinicas_for_sistema("biodata")
        return row + 1

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
        win = self._relatorio_win
        if win is not None and win.is_open:
            win.apply_rows(snap.rows)
            win.present()
            return
        win = RelatorioLoteWindow(self, title=f"{APP_NAME} — Relatório do lote")
        win.apply_rows(snap.rows)
        self._relatorio_win = win
        win.present()

    def _refresh_lote_panel(self) -> Optional[LoteSnapshot]:
        panel = self._lote_panel
        if panel is None:
            return None
        snap = load_lote_snapshot(self._resolve_config_path())
        panel.apply_snapshot(snap)
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
        dados = {
            key: self._entries[key].get().strip()
            for key in DADOS_FIXOS_UI_KEYS
            if key in self._entries
        }
        dados["tipo_apac"] = self.opt_tipo_apac.get().strip()
        dados["cod_orgao_emiss"] = codigo_orgao_emiss(self.opt_orgao_emiss.get())
        sistema = normalizar_sistema_origem(self.opt_sistema.get())
        clinica = self.opt_clinica.get().strip()
        if clinica == "—":
            clinica = ""
        return UiFormData(
            sistema_origem=sistema,
            clinica_id=clinica,
            planilha_caminho=self._entries["planilha_caminho"].get().strip(),
            planilha_prontuarios_caminho=self._entries[
                "planilha_prontuarios_caminho"
            ]
            .get()
            .strip(),
            paciente_inicio=self._entries["paciente_inicio"].get().strip(),
            dados_fixos=dados,
        )

    def _fill_form(self, form: UiFormData) -> None:
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

        mapping = {
            "planilha_caminho": form.planilha_caminho,
            "planilha_prontuarios_caminho": form.planilha_prontuarios_caminho,
            "paciente_inicio": form.paciente_inicio,
            **form.dados_fixos_completos(),
        }
        for key, valor in mapping.items():
            if key in {"tipo_apac", "cod_orgao_emiss"}:
                continue
            entry = self._entries.get(key)
            if entry is None:
                continue
            entry.delete(0, "end")
            entry.insert(0, valor)

        tipo = str(form.dados_fixos.get("tipo_apac") or "").strip()
        self.opt_tipo_apac.set(tipo if tipo in {"1", "3"} else "3")

        orgao_tipo = tipo_orgao_emiss(
            str(form.dados_fixos.get("cod_orgao_emiss") or "")
        )
        self.opt_orgao_emiss.set(orgao_tipo)
        self._sync_orgao_emiss_codigo(orgao_tipo)

        self._apply_cnes_for_clinica(self.opt_clinica.get())

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
        self._refresh_lote_panel()

    def _browse_planilha(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecionar planilha",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
        )
        if not path:
            return
        entry = self._entries["planilha_caminho"]
        entry.delete(0, "end")
        entry.insert(0, path)

    def _browse_planilha_prontuarios(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecionar planilha de prontuários",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
        )
        if not path:
            return
        entry = self._entries["planilha_prontuarios_caminho"]
        entry.delete(0, "end")
        entry.insert(0, path)

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        state = "disabled" if running else "normal"
        for btn in (self.btn_open_apac, self.btn_export_set):
            btn.configure(state=state)
        self.btn_cancel.configure(state="normal" if running else "disabled")
        if running:
            self._refresh_lote_panel()
            self._schedule_lote_poll()
        else:
            self._stop_lote_poll()
            snap = self._refresh_lote_panel()
            if snap is not None and linhas_com_problema(snap.rows):
                self._show_relatorio()

    def _export_set(self) -> None:
        """Copia o staging .SET para o destino escolhido pelo usuario."""
        from apac_bot.config import load_config
        from apac_bot.set_layout import nome_arquivo_set
        from apac_bot.set_pipeline import caminho_staging

        try:
            cfg = load_config(self._resolve_config_path())
        except Exception as exc:
            messagebox.showerror("Exportar SET", str(exc))
            return
        staging = caminho_staging(cfg)
        if not staging.is_file():
            messagebox.showwarning(
                "Exportar SET",
                "Nenhum arquivo gerado ainda.\n"
                "Execute «Iniciar» antes de exportar.",
            )
            return
        comp = str(cfg.export_set.get("competencia_padrao") or "202609")
        prefixo = str(cfg.export_set.get("prefixo_arquivo") or "APOFTAL")
        default_name = nome_arquivo_set(comp, prefixo)
        destino = filedialog.asksaveasfilename(
            title="Salvar arquivo SET",
            defaultextension=".SET",
            initialfile=default_name,
            filetypes=[("Arquivo SET", "*.SET"), ("Todos", "*.*")],
        )
        if not destino:
            return
        dest = Path(destino)
        if dest.suffix.upper() != ".SET":
            dest = dest.with_suffix(".SET")
        try:
            dest.write_bytes(staging.read_bytes())
        except OSError as exc:
            messagebox.showerror("Exportar SET", f"Falha ao salvar:\n{exc}")
            return
        self._append_log(f"[UI] SET exportado: {dest}\n")
        messagebox.showinfo("Exportar SET", f"Arquivo salvo em:\n{dest}")

    def _cancel_job(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self._append_log("[UI] Cancelando processo…\n")
        try:
            proc.terminate()
        except OSError as exc:
            self._append_log(f"[UI] Falha ao cancelar: {exc}\n")

    def _run_cli(self, command: str) -> None:
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

        cmd = [sys.executable, "-m", "apac_bot", command, "--config", str(path)]
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
