"""Painel de progresso do lote: barra, tabela, histórico e relatório."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import customtkinter as ctk

from apac_bot.models import EstadoLancamento
from apac_bot.ui import theme
from apac_bot.ui.lote_data import (
    ESTADOS_PROBLEMA,
    LoteRow,
    LoteSnapshot,
    export_lote_csv,
    filtrar_linhas_lote,
    format_resumo_lote,
    status_label,
)

_STATUS_FG: dict[EstadoLancamento, str] = {
    EstadoLancamento.CONCLUIDO: "#1F6B3A",
    EstadoLancamento.AGUARDANDO_REVISAO: "#9A5B00",
    EstadoLancamento.EM_PROCESSAMENTO: "#1A3D6E",
    EstadoLancamento.PENDENTE: "#555555",
    EstadoLancamento.ERRO: "#8B1A1A",
    EstadoLancamento.SALVAMENTO_INCERTO: "#7A4A00",
}

_BADGE_PREFIX: dict[EstadoLancamento, str] = {
    EstadoLancamento.CONCLUIDO: "✓ ",
    EstadoLancamento.AGUARDANDO_REVISAO: "◷ ",
    EstadoLancamento.EM_PROCESSAMENTO: "◉ ",
    EstadoLancamento.PENDENTE: "··· ",
    EstadoLancamento.ERRO: "! ",
    EstadoLancamento.SALVAMENTO_INCERTO: "? ",
}

_COL_IDS = ("prontuario", "nome", "numero_apac", "status")
_HEADERS = ("Prontuário", "Nome", "Número APAC", "Status")
_COL_WIDTHS = (110, 220, 160, 140)
# Treeview.height = linhas de dados visíveis (padrão ttk é 10 ≈ 320px).
_TABLE_VISIBLE_ROWS = 3

_REL_COL_IDS = ("prontuario", "nome", "numero_apac", "status", "motivo")
_REL_HEADERS = ("Prontuário", "Nome", "Número APAC", "Status", "Motivo")
_REL_COL_WIDTHS = (100, 400, 160, 120, 220)
_REL_TABLE_VISIBLE_ROWS = 12


class LotePanel(ctk.CTkFrame):
    """Card com barra de progresso + tabela e links de histórico/relatório."""

    def __init__(
        self,
        master: Any,
        *,
        on_ver_historico: Callable[[], None],
        on_ver_relatorio: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        opts = {
            "fg_color": theme.SURFACE,
            "corner_radius": theme.RADIUS_CARD,
            "border_width": 1,
            "border_color": theme.BORDER,
        }
        opts.update(kwargs)
        super().__init__(master, **opts)
        self._on_ver_historico = on_ver_historico
        self._on_ver_relatorio = on_ver_relatorio
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        pad = theme.PAD_CARD
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 8))
        head.grid_columnconfigure(0, weight=1)

        self.lbl_progress = ctk.CTkLabel(
            head,
            text="0 de 0 lançamentos concluídos",
            font=theme.font_section(),
            text_color=theme.BRAND_FG,
            anchor="w",
        )
        self.lbl_progress.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(
            head,
            height=10,
            corner_radius=5,
            progress_color=theme.BRAND_ACCENT,
            fg_color=theme.DIVIDER,
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew")
        self.progress_bar.set(0)

        table_wrap = ctk.CTkFrame(
            self,
            fg_color=theme.SURFACE,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER,
        )
        table_wrap.grid(row=1, column=0, sticky="ew", padx=pad, pady=(4, 0))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=0)

        style = ttk.Style(self)
        theme.configure_lote_treeview(style)

        self.tree = ttk.Treeview(
            table_wrap,
            columns=_COL_IDS,
            show="headings",
            selectmode="browse",
            style="Lote.Treeview",
            height=_TABLE_VISIBLE_ROWS,
        )
        for col_id, title, width in zip(_COL_IDS, _HEADERS, _COL_WIDTHS):
            self.tree.heading(col_id, text=title, anchor="w")
            stretch = col_id == "nome"
            self.tree.column(col_id, width=width, minwidth=80, anchor="w", stretch=stretch)

        self.tree.tag_configure("highlight", background=theme.ROW_HIGHLIGHT)
        for estado, fg in _STATUS_FG.items():
            self.tree.tag_configure(estado.value, foreground=fg)

        scrollbar = ttk.Scrollbar(
            table_wrap, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="ew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Overlay centralizado no estado sem planilha (Treeview não centra bem entre cols).
        self.lbl_empty_msg = ctk.CTkLabel(
            table_wrap,
            text="",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="center",
            justify="center",
        )

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=pad, pady=(8, pad))
        foot.grid_columnconfigure(0, weight=1)

        top_line = ctk.CTkFrame(foot, fg_color=theme.DIVIDER, height=1)
        top_line.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.lbl_etapa = ctk.CTkLabel(
            foot,
            text="Última etapa: —",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="w",
        )
        self.lbl_etapa.grid(row=1, column=0, sticky="w")

        self.btn_relatorio = theme.btn_link(
            foot, "Relatório do lote", command=self._on_ver_relatorio
        )
        self.btn_relatorio.grid(row=1, column=1, sticky="e", padx=(8, 0))

        self.btn_historico = theme.btn_link(
            foot, "Ver histórico", command=self._on_ver_historico
        )
        self.btn_historico.grid(row=1, column=2, sticky="e", padx=(8, 0))

        self.lbl_erro = ctk.CTkLabel(
            self,
            text="",
            text_color=theme.WARNING,
            font=theme.font_subtitle(),
            wraplength=720,
            justify="left",
            anchor="w",
        )
        # Só entra no grid quando houver erro — evita faixa vazia no rodapé.
        self._erro_grid = {"row": 3, "column": 0, "sticky": "ew", "padx": pad, "pady": (0, pad)}

    def apply_snapshot(self, snap: LoteSnapshot) -> None:
        total = max(snap.total, 0)
        done = max(snap.concluidos, 0)
        self.lbl_progress.configure(
            text=f"{done} de {total} lançamentos concluídos"
        )
        if total <= 0:
            self.progress_bar.set(0)
        else:
            self.progress_bar.set(min(done / total, 1.0))

        if snap.ultima_etapa:
            self.lbl_etapa.configure(text=f"Última etapa: {snap.ultima_etapa}")
        else:
            self.lbl_etapa.configure(text="Última etapa: —")

        if snap.erro:
            self.lbl_erro.configure(text=snap.erro)
            self.lbl_erro.grid(**self._erro_grid)
        else:
            self.lbl_erro.configure(text="")
            self.lbl_erro.grid_remove()

        self._render_rows(snap.rows, mensagem_tabela=snap.mensagem_tabela)

    def _render_rows(
        self,
        rows: tuple[LoteRow, ...],
        *,
        mensagem_tabela: str | None = None,
    ) -> None:
        self.tree.delete(*self.tree.get_children())
        if not rows and mensagem_tabela:
            self.lbl_empty_msg.configure(text=mensagem_tabela)
            self.lbl_empty_msg.place(relx=0.5, rely=0.55, anchor="center")
            self.lbl_empty_msg.lift()
            return
        self.lbl_empty_msg.place_forget()
        self.lbl_empty_msg.configure(text="")
        for row in rows:
            prefix = _BADGE_PREFIX.get(row.estado, "")
            status_text = f"{prefix}{status_label(row.estado)}"
            values = (
                row.prontuario or "—",
                row.nome or "—",
                row.numero_apac or "—",
                status_text,
            )
            tags: list[str] = [row.estado.value]
            if row.highlight:
                tags.append("highlight")
            self.tree.insert("", "end", values=values, tags=tuple(tags))


class RelatorioLoteWindow(ctk.CTkToplevel):
    """Janela com status e motivo por lançamento; exportação CSV."""

    def __init__(self, master: ctk.CTk, *, title: str = "Relatório do lote") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("1120x520")
        self.minsize(640, 400)
        self.configure(fg_color=theme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._rows: tuple[LoteRow, ...] = ()
        self._filtered_rows: tuple[LoteRow, ...] = ()
        self._closed = False

        hdr = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr,
            text=title,
            font=theme.font_section(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        self.lbl_resumo = ctk.CTkLabel(
            hdr,
            text="0 total",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="w",
        )
        self.lbl_resumo.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        self.entry_busca = theme.style_entry(
            hdr,
            placeholder_text="Buscar por nome, APAC, prontuário ou status…",
        )
        self.entry_busca.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        self.entry_busca.bind("<KeyRelease>", self._on_busca_changed)

        self.lbl_exibindo = ctk.CTkLabel(
            hdr,
            text="",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="w",
        )
        self.lbl_exibindo.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 10))

        table_wrap = ctk.CTkFrame(
            self,
            fg_color=theme.SURFACE,
            corner_radius=theme.RADIUS_CONTROL,
            border_width=1,
            border_color=theme.BORDER,
        )
        table_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style(self)
        theme.configure_lote_treeview(style)

        self.tree = ttk.Treeview(
            table_wrap,
            columns=_REL_COL_IDS,
            show="headings",
            selectmode="browse",
            style="Lote.Treeview",
            height=_REL_TABLE_VISIBLE_ROWS,
        )
        for col_id, title_col, width in zip(
            _REL_COL_IDS, _REL_HEADERS, _REL_COL_WIDTHS
        ):
            self.tree.heading(col_id, text=title_col, anchor="w")
            stretch = col_id == "motivo"
            self.tree.column(
                col_id, width=width, minwidth=80, anchor="w", stretch=stretch
            )
        self.tree.tag_configure("problema", background=theme.ROW_HIGHLIGHT)
        for estado, fg in _STATUS_FG.items():
            self.tree.tag_configure(estado.value, foreground=fg)

        scrollbar = ttk.Scrollbar(
            table_wrap, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=4)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        actions.grid_columnconfigure(0, weight=1)
        theme.btn_secondary(
            actions, "Exportar CSV", command=self._export_csv, width=130
        ).grid(row=0, column=1, padx=(0, 8))
        theme.btn_primary(actions, "Fechar", command=self._on_close, width=100).grid(
            row=0, column=2
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.transient(master)
        self.after(50, self.present)

    def present(self) -> None:
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            # Widget já destruído pelo gerenciador de janelas
            return
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        self._closed = True
        self.destroy()

    @property
    def is_open(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except Exception:
            # Widget já destruído pelo gerenciador de janelas
            return False

    def apply_rows(self, rows: tuple[LoteRow, ...]) -> None:
        if not self.is_open:
            return
        self._rows = rows
        self.lbl_resumo.configure(text=format_resumo_lote(rows))
        self._render_filtered()

    def _on_busca_changed(self, _event: Any = None) -> None:
        if not self.is_open:
            return
        self._render_filtered()

    def _query_busca(self) -> str:
        try:
            return self.entry_busca.get()
        except Exception:
            # Widget já destruído
            return ""

    def _render_filtered(self) -> None:
        if not self.is_open:
            return
        query = self._query_busca()
        filtered = filtrar_linhas_lote(self._rows, query)
        self._filtered_rows = filtered
        total = len(self._rows)
        shown = len(filtered)
        if query.strip() and shown != total:
            self.lbl_exibindo.configure(text=f"Exibindo {shown} de {total}")
        else:
            self.lbl_exibindo.configure(text="")

        self.tree.delete(*self.tree.get_children())
        for row in filtered:
            prefix = _BADGE_PREFIX.get(row.estado, "")
            status_text = f"{prefix}{status_label(row.estado)}"
            values = (
                row.prontuario or "—",
                row.nome or "—",
                row.numero_apac or "—",
                status_text,
                row.motivo or "—",
            )
            tags: list[str] = [row.estado.value]
            if row.estado in ESTADOS_PROBLEMA:
                tags.append("problema")
            self.tree.insert("", "end", values=values, tags=tuple(tags))

    def _export_csv(self) -> None:
        rows = self._filtered_rows
        if not rows:
            messagebox.showwarning(
                "Exportar CSV",
                "Não há lançamentos para exportar.",
                parent=self,
            )
            return
        destino = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar relatório do lote",
            defaultextension=".csv",
            initialfile="relatorio_lote.csv",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if not destino:
            return
        dest = Path(destino)
        if dest.suffix.lower() != ".csv":
            dest = dest.with_suffix(".csv")
        try:
            export_lote_csv(dest, rows)
        except OSError as exc:
            messagebox.showerror(
                "Exportar CSV",
                f"Falha ao salvar:\n{exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Exportar CSV",
            f"Arquivo salvo em:\n{dest}",
            parent=self,
        )


class HistoricoLogWindow(ctk.CTkToplevel):
    """Janela com o buffer de log da UI."""

    def __init__(self, master: ctk.CTk, *, title: str = "Histórico") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("720x420")
        self.minsize(480, 280)
        self.configure(fg_color=theme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr,
            text=title,
            font=theme.font_section(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=12)

        self.log_box = ctk.CTkTextbox(
            self,
            font=theme.font_mono(),
            fg_color=theme.SURFACE,
            text_color=theme.BRAND_FG,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=theme.RADIUS_CONTROL,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._closed = False
        # CTkToplevel no Windows faz withdraw() no titlebar; reapresentar depois.
        self.transient(master)
        self.after(50, self.present)

    def present(self) -> None:
        """Garante que a janela fique visível e em foco (após withdraw do CTk)."""
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            # Widget já destruído pelo gerenciador de janelas
            return
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        self._closed = True
        self.destroy()

    @property
    def is_open(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except Exception:
            # Widget já destruído pelo gerenciador de janelas
            return False

    def set_text(self, text: str) -> None:
        if not self.is_open:
            return
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def append_text(self, text: str) -> None:
        if not self.is_open:
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


_MSG_ARQUIVO_AUSENTE = (
    "Nenhum arquivo gerado ainda.\n"
    "Execute «Iniciar» para começar a montar o arquivo."
)


class SetPreviewWindow(ctk.CTkToplevel):
    """Janela read-only com o conteúdo do staging (atualiza sob demanda/poll)."""

    def __init__(
        self,
        master: ctk.CTk,
        *,
        staging_path: Path,
        title: str = "Arquivo parcial",
        poll_ms: int = 1000,
    ) -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("780x480")
        self.minsize(520, 320)
        self.configure(fg_color=theme.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._staging_path = Path(staging_path)
        self._poll_ms = max(500, int(poll_ms))
        self._poll_after_id: str | None = None
        self._closed = False
        self._last_mtime_ns: int | None = None
        self._last_size: int | None = None

        hdr = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr,
            text=title,
            font=theme.font_section(),
            text_color=theme.BRAND_FG,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=12)
        self.lbl_status = ctk.CTkLabel(
            hdr,
            text="",
            font=theme.font_subtitle(),
            text_color=theme.BRAND_MUTED,
            anchor="e",
        )
        self.lbl_status.grid(row=0, column=1, sticky="e", padx=14, pady=12)

        self.text_box = ctk.CTkTextbox(
            self,
            font=theme.font_mono(),
            fg_color=theme.SURFACE,
            text_color=theme.BRAND_FG,
            border_width=1,
            border_color=theme.BORDER,
            corner_radius=theme.RADIUS_CONTROL,
            wrap="none",
        )
        self.text_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.text_box.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.transient(master)
        self.after(50, self.present)
        self.refresh()
        self._schedule_poll()

    def present(self) -> None:
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        self._stop_poll()
        self._closed = True
        self.destroy()

    @property
    def is_open(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _stop_poll(self) -> None:
        if self._poll_after_id is None:
            return
        try:
            self.after_cancel(self._poll_after_id)
        except Exception:
            # after id já inválido
            pass
        self._poll_after_id = None

    def _schedule_poll(self) -> None:
        self._stop_poll()
        if not self.is_open:
            return
        self._poll_after_id = self.after(self._poll_ms, self._poll_tick)

    def _poll_tick(self) -> None:
        self._poll_after_id = None
        if not self.is_open:
            return
        self.refresh()
        self._schedule_poll()

    def set_staging_path(self, path: Path) -> None:
        self._staging_path = Path(path)
        self._last_mtime_ns = None
        self._last_size = None
        self.refresh()

    def _set_text(self, text: str) -> None:
        if not self.is_open:
            return
        self.text_box.configure(state="normal")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("end", text)
        self.text_box.see("end")
        self.text_box.configure(state="disabled")

    def refresh(self) -> None:
        """Relê o staging se mudou; mantém scroll no fim."""
        if not self.is_open:
            return
        path = self._staging_path
        if not path.is_file():
            self.lbl_status.configure(text="aguardando…")
            self._set_text(_MSG_ARQUIVO_AUSENTE)
            self._last_mtime_ns = None
            self._last_size = None
            return
        try:
            st = path.stat()
            mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
            size = st.st_size
            if (
                self._last_mtime_ns == mtime_ns
                and self._last_size == size
            ):
                return
            raw = path.read_bytes()
            text = raw.decode("latin-1", errors="replace")
        except OSError as exc:
            self.lbl_status.configure(text="erro de leitura")
            self._set_text(f"Falha ao ler staging:\n{exc}")
            return
        self._last_mtime_ns = mtime_ns
        self._last_size = size
        self.lbl_status.configure(text=f"{size} bytes")
        self._set_text(text)
