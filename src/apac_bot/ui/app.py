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
    SISTEMAS_UI,
    UI_SECOES_TELA,
    ConfigIoError,
    UiFormData,
    aplicar_defaults_clinica,
    default_config_path,
    load_form,
    normalizar_sistema_origem,
    save_form,
    secrets_missing,
    sistema_ui_label,
    validate_form,
)

# Marca / splash
APP_NAME = "SIS DG"
APP_TAGLINE = "Sistema de Inteligência em Saúde DG"
APP_VERSION = "1.0.0"
BRAND_FG = "#1a2a38"
BRAND_MUTED = "#5a6b7a"
BRAND_ACCENT = "#103055"
SPLASH_BG = "#ffffff"
SPLASH_BG_DARK = "#152a42"

# Estilos por variante (1/2 claras, 3 escura). rely ≈ posição do CTA na arte.
SPLASH_VARIANTS: dict[int, dict] = {
    1: {
        "files": ("splash_welcome.png", "splash_welcome.jpg"),
        "window_bg": SPLASH_BG,
        "btn_fg": BRAND_ACCENT,
        "btn_hover": "#0a2038",
        "btn_text": "#ffffff",
        "badge_fg": BRAND_ACCENT,
        "badge_text": "#ffffff",
        "btn_rely": 0.63,
        "selector_fg": BRAND_ACCENT,
        "selector_text": "#ffffff",
        "selector_idle": "#d0d8e0",
        "selector_idle_text": BRAND_ACCENT,
    },
    2: {
        "files": ("splash_v2.png", "splash_v2.jpg"),
        "window_bg": SPLASH_BG,
        "btn_fg": BRAND_ACCENT,
        "btn_hover": "#0a2038",
        "btn_text": "#ffffff",
        "badge_fg": BRAND_ACCENT,
        "badge_text": "#ffffff",
        "btn_rely": 0.75,
        "selector_fg": BRAND_ACCENT,
        "selector_text": "#ffffff",
        "selector_idle": "#d0d8e0",
        "selector_idle_text": BRAND_ACCENT,
    },
    3: {
        "files": ("splash_v3.png", "splash_v3.jpg"),
        "window_bg": SPLASH_BG_DARK,
        "btn_fg": "#ffffff",
        "btn_hover": "#e8eef4",
        "btn_text": BRAND_ACCENT,
        "badge_fg": "#ffffff",
        "badge_text": BRAND_ACCENT,
        "btn_rely": 0.81,
        "selector_fg": "#ffffff",
        "selector_text": BRAND_ACCENT,
        "selector_idle": "#2a4060",
        "selector_idle_text": "#ffffff",
    },
}

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _splash_bg_path(variant: int = 1) -> Optional[Path]:
    """Resolve PNG (preferido) ou JPG da variante de splash."""
    meta = SPLASH_VARIANTS.get(variant) or SPLASH_VARIANTS[1]
    assets = _assets_dir()
    for name in meta["files"]:
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
        self._job_running = False
        self._splash_pil: Optional[Image.Image] = None
        self._splash_bg_image: Optional[ctk.CTkImage] = None
        self._splash_bg_label: Optional[ctk.CTkLabel] = None
        self._splash_btn: Optional[ctk.CTkButton] = None
        self._splash_version: Optional[ctk.CTkLabel] = None
        self._splash_frame: Optional[ctk.CTkFrame] = None
        self._splash_selector_btns: dict[int, ctk.CTkButton] = {}
        self._splash_variant = 1
        self._splash_mode = False
        self._resize_after_id: Optional[str] = None
        self._last_bg_size: tuple[int, int] = (0, 0)
        self._main_ready = False

        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        # Splash fixa 1024x576 (proporção das artes v2/v3 — evita logo achatada)
        self.geometry("1024x576")
        self.minsize(1024, 576)
        self.maxsize(1024, 576)
        self.resizable(False, False)
        self.configure(fg_color=SPLASH_BG)
        self._show_splash()

    def _clear_root(self) -> None:
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None
        self.unbind("<Configure>")
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

    def _splash_meta(self) -> dict:
        return SPLASH_VARIANTS.get(self._splash_variant) or SPLASH_VARIANTS[1]

    def _splash_apply_layout(self) -> None:
        self._resize_after_id = None
        if not self._splash_mode:
            return
        win_w = max(self.winfo_width(), 1)
        win_h = max(self.winfo_height(), 1)
        # Ignora tamanho pré-mapeamento (1x1) que deixava o fundo “branco”
        if win_w >= 200 and win_h >= 200:
            self._resize_splash_bg(win_w, win_h)
        meta = self._splash_meta()
        if self._splash_btn is not None:
            compact = win_h < 500
            self._splash_btn.configure(
                width=200 if compact else 260,
                height=40 if compact else 48,
            )
            self._splash_btn.place(
                relx=0.5, rely=float(meta["btn_rely"]), anchor="center"
            )
        if self._splash_version is not None:
            self._splash_version.place(relx=0.02, rely=0.97, anchor="sw")
        if self._splash_selector_btns:
            gap = 0.038
            for i, n in enumerate((1, 2, 3)):
                btn = self._splash_selector_btns.get(n)
                if btn is not None:
                    btn.place(
                        relx=0.98 - (2 - i) * gap,
                        rely=0.03,
                        anchor="ne",
                    )
        self._lift_splash_controls()

    def _resize_splash_bg(self, win_w: int, win_h: int) -> None:
        if self._splash_pil is None or self._splash_bg_label is None:
            return
        size = (max(win_w, 1), max(win_h, 1))
        if size == self._last_bg_size:
            return
        self._last_bg_size = size
        meta = self._splash_meta()
        filled = _pil_fill(
            self._splash_pil, size[0], size[1], fill=meta["window_bg"]
        )
        self._splash_bg_image = ctk.CTkImage(
            light_image=filled,
            dark_image=filled,
            size=size,
        )
        self._splash_bg_label.configure(image=self._splash_bg_image, text="")
        self._splash_bg_label.place(x=0, y=0, relwidth=1, relheight=1)

    def _show_splash(self) -> None:
        """Splash full-bleed com arte da variante + CTA e badge reais."""
        self._clear_root()
        self._splash_mode = True
        self._splash_bg_label = None
        self._splash_bg_image = None
        self._splash_btn = None
        self._splash_version = None
        self._splash_selector_btns = {}
        self._last_bg_size = (0, 0)
        meta = self._splash_meta()
        self.geometry("1024x576")
        self.minsize(1024, 576)
        self.maxsize(1024, 576)
        self.resizable(False, False)
        self.configure(fg_color=meta["window_bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Frame “oco”: sem cor própria — a arte CTkLabel é o fundo
        frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self._splash_frame = frame

        self._load_splash_background(frame, meta)
        self._build_splash_controls(frame, meta)

        self.bind("<Configure>", self._on_splash_configure)
        self.after(50, self._splash_apply_layout)
        self.after(200, self._splash_apply_layout)

    def _load_splash_background(self, frame: ctk.CTkFrame, meta: dict) -> None:
        bg_path = _splash_bg_path(self._splash_variant)
        self._last_bg_size = (0, 0)
        if bg_path is not None and bg_path.is_file():
            self._splash_pil = Image.open(bg_path).convert("RGB")
            # Janela splash fixa 1024x576
            win_w = max(self.winfo_width(), 1)
            win_h = max(self.winfo_height(), 1)
            if win_w < 200 or win_h < 200:
                win_w, win_h = 1024, 576
            filled = _pil_fill(
                self._splash_pil, win_w, win_h, fill=meta["window_bg"]
            )
            self._splash_bg_image = ctk.CTkImage(
                light_image=filled,
                dark_image=filled,
                size=(win_w, win_h),
            )
            label_ok = False
            if self._splash_bg_label is not None:
                try:
                    label_ok = bool(self._splash_bg_label.winfo_exists())
                except Exception:
                    label_ok = False
            if not label_ok:
                self._splash_bg_label = ctk.CTkLabel(
                    frame,
                    text="",
                    image=self._splash_bg_image,
                    fg_color=meta["window_bg"],
                    corner_radius=0,
                )
            else:
                self._splash_bg_label.configure(
                    image=self._splash_bg_image,
                    text="",
                    fg_color=meta["window_bg"],
                )
            # place absoluto atrás dos controles (sem lower — CTk canvas quebra stacking)
            self._splash_bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self._splash_pil = None
            self._splash_bg_label = ctk.CTkLabel(
                frame,
                text=f"{APP_NAME}\n{APP_TAGLINE}",
                font=ctk.CTkFont(size=28, weight="bold"),
                text_color=BRAND_FG if self._splash_variant != 3 else "#ffffff",
                fg_color=meta["window_bg"],
                corner_radius=0,
            )
            self._splash_bg_label.place(relx=0.5, rely=0.4, anchor="center")

    def _build_splash_controls(self, frame: ctk.CTkFrame, meta: dict) -> None:
        # Criados DEPOIS do fundo → ficam acima no stacking do CTk
        self._splash_btn = ctk.CTkButton(
            frame,
            text="Acessar sistema",
            width=260,
            height=48,
            corner_radius=24,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=meta["btn_fg"],
            hover_color=meta["btn_hover"],
            text_color=meta["btn_text"],
            command=self._on_comecar,
        )
        self._splash_btn.place(
            relx=0.5, rely=float(meta["btn_rely"]), anchor="center"
        )

        self._splash_version = ctk.CTkLabel(
            frame,
            text=f"Versão {APP_VERSION}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=meta["badge_text"],
            fg_color=meta["badge_fg"],
            corner_radius=6,
            height=26,
            width=110,
        )
        self._splash_version.place(relx=0.02, rely=0.97, anchor="sw")

        for n in (1, 2, 3):
            active = n == self._splash_variant
            btn = ctk.CTkButton(
                frame,
                text=str(n),
                width=32,
                height=28,
                corner_radius=8,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=meta["selector_fg"] if active else meta["selector_idle"],
                hover_color=meta["selector_fg"],
                text_color=(
                    meta["selector_text"] if active else meta["selector_idle_text"]
                ),
                command=lambda v=n: self._set_splash_variant(v),
            )
            self._splash_selector_btns[n] = btn

    def _lift_splash_controls(self) -> None:
        if self._splash_btn is not None:
            self._splash_btn.lift()
        if self._splash_version is not None:
            self._splash_version.lift()
        for btn in self._splash_selector_btns.values():
            btn.lift()

    def _set_splash_variant(self, variant: int) -> None:
        if variant not in SPLASH_VARIANTS or variant == self._splash_variant:
            return
        if not self._splash_mode or self._splash_frame is None:
            return
        self._splash_variant = variant
        meta = self._splash_meta()
        self.configure(fg_color=meta["window_bg"])
        self._load_splash_background(self._splash_frame, meta)
        if self._splash_btn is not None:
            self._splash_btn.configure(
                fg_color=meta["btn_fg"],
                hover_color=meta["btn_hover"],
                text_color=meta["btn_text"],
            )
        if self._splash_version is not None:
            self._splash_version.configure(
                text_color=meta["badge_text"],
                fg_color=meta["badge_fg"],
            )
        for n, btn in self._splash_selector_btns.items():
            active = n == self._splash_variant
            btn.configure(
                fg_color=meta["selector_fg"] if active else meta["selector_idle"],
                hover_color=meta["selector_fg"],
                text_color=(
                    meta["selector_text"] if active else meta["selector_idle_text"]
                ),
            )
        self._last_bg_size = (0, 0)
        self._splash_apply_layout()
        self._lift_splash_controls()

    def _on_comecar(self) -> None:
        self._show_main()

    def _show_main(self) -> None:
        self._splash_mode = False
        self._clear_root()
        self.geometry("980x780")
        self.minsize(980, 780)
        self.maxsize(980, 780)
        self.resizable(False, False)
        # Volta ao tema padrão do CustomTkinter (dark)
        self.configure(fg_color=("gray95", "gray95"))
        self.title(f"{APP_NAME} — Automação APAC")
        self._build()
        self._load_into_form()
        if not self._main_ready:
            self.after(120, self._drain_log_queue)
            self._main_ready = True

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            top,
            text=f"{APP_NAME} — configuração do lote",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ctk.CTkButton(
            top, text="Recarregar", width=100, command=self._load_into_form
        ).grid(row=0, column=1, padx=(4, 8), pady=8)

        body = ctk.CTkScrollableFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0)

        row = 0
        ctk.CTkLabel(
            body, text="Clínica / planilha", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 8))
        row += 1

        row = self._add_sistema_clinica_planilha_row(body, row)
        row = self._add_fields_grid(body, row, ("paciente_inicio",))

        for titulo, keys in UI_SECOES_TELA:
            ctk.CTkLabel(
                body, text=titulo, font=ctk.CTkFont(size=15, weight="bold")
            ).grid(row=row, column=0, columnspan=3, sticky="w", padx=4, pady=(12, 4))
            row += 1
            n_cols = 5 if titulo == "Procedimentos" else 3
            row = self._add_fields_grid(body, row, keys, cols=n_cols)

        self._apply_cnes_for_clinica(self.opt_clinica.get())

        self.lbl_aviso = ctk.CTkLabel(
            body, text="", text_color="#c9a227", wraplength=700, justify="left"
        )
        self.lbl_aviso.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=4, pady=(12, 4)
        )

        actions = ctk.CTkFrame(self)
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        for i in range(5):
            actions.grid_columnconfigure(i, weight=1)

        self.btn_salvar = ctk.CTkButton(actions, text="Salvar", command=self._on_salvar)
        self.btn_salvar.grid(row=0, column=0, padx=4, pady=8, sticky="ew")
        self.btn_validate = ctk.CTkButton(
            actions, text="Validar", command=lambda: self._run_cli("validate")
        )
        self.btn_validate.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self.btn_open_apac = ctk.CTkButton(
            actions,
            text="Iniciar lote (open-apac)",
            command=lambda: self._run_cli("open-apac"),
        )
        self.btn_open_apac.grid(row=0, column=2, padx=4, pady=8, sticky="ew")
        self.btn_status = ctk.CTkButton(
            actions, text="Status", command=lambda: self._run_cli("status")
        )
        self.btn_status.grid(row=0, column=3, padx=4, pady=8, sticky="ew")
        self.btn_cancel = ctk.CTkButton(
            actions,
            text="Cancelar",
            fg_color="#8b3a3a",
            hover_color="#6e2e2e",
            command=self._cancel_job,
            state="disabled",
        )
        self.btn_cancel.grid(row=0, column=4, padx=4, pady=8, sticky="ew")

        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_frame, text="Log", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        self.log_box = ctk.CTkTextbox(
            log_frame, height=180, font=ctk.CTkFont(family="Consolas", size=12)
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.log_box.configure(state="disabled")

    def _add_fields_grid(
        self,
        parent: ctk.CTkScrollableFrame,
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
            wrap.grid(row=row, column=0, columnspan=3, sticky="ew", padx=0, pady=4)
            for i in range(cols):
                wrap.grid_columnconfigure(i, weight=1)
            for col, key in enumerate(chunk):
                cell = ctk.CTkFrame(wrap, fg_color="transparent")
                cell.grid(row=0, column=col, sticky="ew", padx=4, pady=0)
                cell.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(cell, text=labels.get(key, key)).grid(
                    row=0, column=0, sticky="w", padx=0, pady=(0, 2)
                )
                if key == "tipo_apac":
                    self.opt_tipo_apac = ctk.CTkOptionMenu(
                        cell, values=["1", "3"], width=80
                    )
                    self.opt_tipo_apac.grid(
                        row=1, column=0, sticky="w", padx=0, pady=0
                    )
                    self.opt_tipo_apac.set("3")
                else:
                    entry = ctk.CTkEntry(cell)
                    entry.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
                    self._entries[key] = entry
            row += 1
        return row

    def _add_sistema_clinica_planilha_row(
        self, parent: ctk.CTkScrollableFrame, row: int
    ) -> int:
        """Sistema | Clínica | Planilha — label em cima; selects estreitos."""
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=0, columnspan=3, sticky="ew", padx=0, pady=4)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=0)
        wrap.grid_columnconfigure(2, weight=1)

        col_sistema = ctk.CTkFrame(wrap, fg_color="transparent")
        col_sistema.grid(row=0, column=0, sticky="nw", padx=(4, 6), pady=0)
        ctk.CTkLabel(col_sistema, text="Sistema").grid(
            row=0, column=0, sticky="w", padx=0, pady=(0, 2)
        )
        self.opt_sistema = ctk.CTkOptionMenu(
            col_sistema,
            values=list(SISTEMAS_UI),
            command=self._on_sistema_changed,
            width=150,
        )
        self.opt_sistema.grid(row=1, column=0, sticky="w", padx=0, pady=0)
        self.opt_sistema.set("BIODATA")

        col_clinica = ctk.CTkFrame(wrap, fg_color="transparent")
        col_clinica.grid(row=0, column=1, sticky="nw", padx=(6, 6), pady=0)
        ctk.CTkLabel(col_clinica, text="ID da clínica").grid(
            row=0, column=0, sticky="w", padx=0, pady=(0, 2)
        )
        self.opt_clinica = ctk.CTkOptionMenu(
            col_clinica,
            values=["oftalmocentro91"],
            width=160,
            command=self._on_clinica_changed,
        )
        self.opt_clinica.grid(row=1, column=0, sticky="w", padx=0, pady=0)

        col_planilha = ctk.CTkFrame(wrap, fg_color="transparent")
        col_planilha.grid(row=0, column=2, sticky="ew", padx=(6, 4), pady=0)
        col_planilha.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(col_planilha, text="Planilha (.xlsx)").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=0, pady=(0, 2)
        )
        entry = ctk.CTkEntry(col_planilha)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=0)
        self._entries["planilha_caminho"] = entry
        ctk.CTkButton(
            col_planilha, text="Browse…", width=80, command=self._browse_planilha
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
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.after(120, self._drain_log_queue)

    def _resolve_config_path(self) -> Path:
        return Path(self.config_path)

    def _collect_form(self) -> UiFormData:
        dados = {
            key: self._entries[key].get().strip()
            for key in DADOS_FIXOS_UI_KEYS
            if key in self._entries
        }
        dados["tipo_apac"] = self.opt_tipo_apac.get().strip()
        sistema = normalizar_sistema_origem(self.opt_sistema.get())
        clinica = self.opt_clinica.get().strip()
        if clinica == "—":
            clinica = ""
        return UiFormData(
            sistema_origem=sistema,
            clinica_id=clinica,
            planilha_caminho=self._entries["planilha_caminho"].get().strip(),
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
            "paciente_inicio": form.paciente_inicio,
            **form.dados_fixos_completos(),
        }
        for key, valor in mapping.items():
            if key == "tipo_apac":
                continue
            entry = self._entries.get(key)
            if entry is None:
                continue
            entry.delete(0, "end")
            entry.insert(0, valor)

        tipo = str(form.dados_fixos.get("tipo_apac") or "").strip()
        self.opt_tipo_apac.set(tipo if tipo in {"1", "3"} else "3")

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

    def _on_salvar(self) -> None:
        path = self._resolve_config_path()
        form = self._collect_form()
        erros = validate_form(form)
        if erros:
            messagebox.showerror("Validação", "\n".join(erros))
            return
        try:
            save_form(path, form)
        except ConfigIoError as exc:
            messagebox.showerror("Salvar", str(exc))
            return
        self.config_path = path
        self._append_log(f"[UI] Config salva: {path}\n")
        messagebox.showinfo("Salvar", f"Configuração salva em:\n{path}")

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        state = "disabled" if running else "normal"
        for btn in (
            self.btn_salvar,
            self.btn_validate,
            self.btn_open_apac,
            self.btn_status,
        ):
            btn.configure(state=state)
        self.btn_cancel.configure(state="normal" if running else "disabled")

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
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
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
