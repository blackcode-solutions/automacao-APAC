"""Tokens visuais da marca SIS DG (tela principal / painéis)."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk
from typing import Any, Optional

import customtkinter as ctk

# Marca (alinhada ao splash)
BRAND_FG = "#1a2a38"
BRAND_MUTED = "#5a6b7a"
BRAND_ACCENT = "#103055"
BRAND_HOVER = "#0a2038"

BG = "#F4F6F8"
SURFACE = "#FFFFFF"
BORDER = "#E2E6EC"
DIVIDER = "#EEF1F5"
ROW_HIGHLIGHT = "#FFF6E8"
WARNING = "#B8860B"
DANGER = "#8B3A3A"
DANGER_HOVER = "#6E2E2E"
LINK = "#1A5FB4"

RADIUS_CARD = 12
RADIUS_CONTROL = 8
RADIUS_PILL = 12
PAD_CARD = 14
ENTRY_HEIGHT = 32
BTN_HEIGHT = 34
BTN_HEIGHT_PRIMARY = 38

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"


def font_title() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold")


def font_subtitle() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=12)


def font_section() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold")


def font_body() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=13)


def font_label() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=11)


def font_badge() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold")


def font_mono() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_MONO, size=12)


def configure_lote_treeview(style: ttk.Style) -> None:
    """Aplica cores/fontes da marca ao Treeview do painel de lote."""
    style.theme_use("clam")
    style.configure(
        "Lote.Treeview",
        background=SURFACE,
        foreground=BRAND_FG,
        fieldbackground=SURFACE,
        bordercolor=BORDER,
        borderwidth=1,
        rowheight=32,
        font=(FONT_FAMILY, 13),
    )
    style.configure(
        "Lote.Treeview.Heading",
        background=SURFACE,
        foreground=BRAND_MUTED,
        bordercolor=BORDER,
        borderwidth=0,
        relief="flat",
        font=(FONT_FAMILY, 11),
    )
    style.map(
        "Lote.Treeview",
        background=[("selected", DIVIDER)],
        foreground=[("selected", BRAND_FG)],
    )
    style.map(
        "Lote.Treeview.Heading",
        background=[("active", DIVIDER)],
    )


def make_card(master: Any, **kwargs: Any) -> ctk.CTkFrame:
    opts = {
        "fg_color": SURFACE,
        "corner_radius": RADIUS_CARD,
        "border_width": 1,
        "border_color": BORDER,
    }
    opts.update(kwargs)
    return ctk.CTkFrame(master, **opts)


def style_field_label(master: Any, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        master,
        text=text,
        font=font_label(),
        text_color=BRAND_MUTED,
        anchor="w",
    )


def style_entry(master: Any, **kwargs: Any) -> ctk.CTkEntry:
    opts = {
        "height": ENTRY_HEIGHT,
        "corner_radius": RADIUS_CONTROL,
        "border_color": BORDER,
        "fg_color": SURFACE,
        "text_color": BRAND_FG,
    }
    opts.update(kwargs)
    return ctk.CTkEntry(master, **opts)


def style_option(master: Any, values: list[str], **kwargs: Any) -> ctk.CTkOptionMenu:
    opts = {
        "values": values,
        "height": ENTRY_HEIGHT,
        "corner_radius": RADIUS_CONTROL,
        "fg_color": BRAND_ACCENT,
        "button_color": BRAND_HOVER,
        "button_hover_color": BRAND_HOVER,
        "dropdown_fg_color": SURFACE,
        "dropdown_hover_color": BG,
        "text_color": "#FFFFFF",
    }
    opts.update(kwargs)
    return ctk.CTkOptionMenu(master, **opts)


def btn_primary(
    master: Any,
    text: str,
    command: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> ctk.CTkButton:
    opts = {
        "text": text,
        "command": command,
        "height": BTN_HEIGHT_PRIMARY,
        "corner_radius": RADIUS_CONTROL,
        "fg_color": BRAND_ACCENT,
        "hover_color": BRAND_HOVER,
        "text_color": "#FFFFFF",
        "font": ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
    }
    opts.update(kwargs)
    return ctk.CTkButton(master, **opts)


def btn_secondary(
    master: Any,
    text: str,
    command: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> ctk.CTkButton:
    opts = {
        "text": text,
        "command": command,
        "height": BTN_HEIGHT,
        "corner_radius": RADIUS_CONTROL,
        "fg_color": BG,
        "hover_color": DIVIDER,
        "text_color": BRAND_FG,
        "border_width": 1,
        "border_color": BORDER,
        "font": font_body(),
    }
    opts.update(kwargs)
    return ctk.CTkButton(master, **opts)


def btn_danger(
    master: Any,
    text: str,
    command: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> ctk.CTkButton:
    opts = {
        "text": text,
        "command": command,
        "height": BTN_HEIGHT,
        "corner_radius": RADIUS_CONTROL,
        "fg_color": DANGER,
        "hover_color": DANGER_HOVER,
        "text_color": "#FFFFFF",
        "font": font_body(),
    }
    opts.update(kwargs)
    return ctk.CTkButton(master, **opts)


def btn_link(
    master: Any,
    text: str,
    command: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> ctk.CTkButton:
    opts = {
        "text": text,
        "command": command,
        "height": 28,
        "width": 120,
        "fg_color": "transparent",
        "hover_color": DIVIDER,
        "text_color": LINK,
        "font": font_subtitle(),
    }
    opts.update(kwargs)
    return ctk.CTkButton(master, **opts)
