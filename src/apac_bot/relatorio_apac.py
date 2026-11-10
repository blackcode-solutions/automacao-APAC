"""Relatório de entrega APAC para cliente (SET + falhas do lote)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import PatternFill

from apac_bot.config import (
    MODALIDADE_GLAUCOMA,
    MODALIDADE_PADRAO,
    AppConfig,
    config_dir,
    resolve_path,
)
from apac_bot.models import Lancamento
from apac_bot.normalize import nascimento_ddmmaaaa
from apac_bot.progress import ProgressRecord, ProgressStore
from apac_bot.set_layout import (
    SetLayoutError,
    competencia_aaaamm,
    competencia_mes_anterior,
    ultimo_dia_mes,
)
from apac_bot.set_parse import (
    ParsedPaciente,
    ParsedProc,
    ParsedSet,
    parse_set_file,
)
from apac_bot.sheet import (
    MapaPreviaGlaucoma,
    SheetError,
    carregar_mapa_honorarios,
    carregar_mapa_previa_glaucoma,
    codigo_procedimento_chave,
    listar_lancamentos_a_partir,
    load_lancamentos,
    mapa_previa_glaucoma_de_lancamentos,
    nome_chave_prontuario,
)

SITUACAO_SEM_ERROS = "SEM ERROS"
PREVIA_PLACEHOLDER = "—"
MOTIVO_NAO_INFORMADO = "motivo não informado"
MOTIVO_NAO_PROCESSADO = "não processado"
SISTEMA_RELATORIO = "SIS DG - SISTEMA DE INTELIGÊNCIA EM SAÚDE DG"
_RE_DIGITOS_FINAIS = re.compile(r"\d+$")
# Fundo vermelho claro para linhas COM ERROS (PDF RGB / XLSX hex).
_COR_ERRO_RGB = (255, 204, 204)
_FILL_ERRO_XLSX = PatternFill(fill_type="solid", fgColor="FFCCCC")

_CSV_HEADERS_PADRAO = (
    "competencia",
    "nome",
    "codigo_procedimento",
    "quantidade",
    "cbo",
    "idade",
    "valor",
    "situacao",
)

_CSV_HEADERS_GLAUCOMA = (
    "competencia",
    "nome",
    "codigo_procedimento",
    "valor",
    "situacao",
)


@dataclass(frozen=True, slots=True)
class RelatorioApacMeta:
    sistema: str
    titulo: str
    clinica: str
    cnes: str
    competencia: str
    gerado_em: str


@dataclass(frozen=True, slots=True)
class RelatorioApacRow:
    competencia: str
    nome: str
    codigo_procedimento: str
    quantidade: str
    cbo: str
    idade: str
    previa: str
    situacao: str


@dataclass(frozen=True, slots=True)
class RelatorioApac:
    meta: RelatorioApacMeta
    rows: tuple[RelatorioApacRow, ...]
    total_cnes: float
    modalidade: str = MODALIDADE_PADRAO
    total_nao_lancados: float = 0.0


def format_competencia_mm_aaaa(comp: str) -> str:
    """AAAAMM → MM/AAAA."""
    c = competencia_aaaamm(comp)
    return f"{c[4:6]}/{c[0:4]}"


def format_moeda_br(valor: float) -> str:
    """1127.7 → R$ 1.127,70"""
    inteiro, frac = f"{valor:.2f}".split(".")
    grupos: list[str] = []
    while inteiro:
        grupos.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    corpo = ".".join(reversed(grupos))
    return f"R$ {corpo},{frac}"


def format_previa_valor(valor: float) -> str:
    return format_moeda_br(valor)


def parse_previa_numero(texto: str) -> Optional[float]:
    """Converte texto de prévia (R$ …) em float; None se placeholder."""
    s = (texto or "").strip()
    if not s or s == PREVIA_PLACEHOLDER:
        return None
    limpo = s.replace("R$", "").replace("r$", "").strip().replace(" ", "")
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


def _parse_nascimento_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    s = str(raw).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        y, m, d = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        try:
            return date(y, m, d)
        except ValueError:
            pass
        dd = nascimento_ddmmaaaa(s)
        if dd and len(dd) == 8:
            try:
                return date(int(dd[4:8]), int(dd[2:4]), int(dd[0:2]))
            except ValueError:
                return None
        return None
    dd = nascimento_ddmmaaaa(s)
    if not dd or len(dd) != 8:
        return None
    try:
        return date(int(dd[4:8]), int(dd[2:4]), int(dd[0:2]))
    except ValueError:
        return None


def idade_em(nascimento: Optional[str], ref: date) -> str:
    """Anos completos em `ref`; `—` se nascimento inválido/ausente."""
    nasc = _parse_nascimento_date(nascimento)
    if nasc is None:
        return PREVIA_PLACEHOLDER
    anos = ref.year - nasc.year
    if (ref.month, ref.day) < (nasc.month, nasc.day):
        anos -= 1
    if anos < 0:
        return PREVIA_PLACEHOLDER
    return str(anos)


def ref_idade_competencia(competencia: str) -> date:
    c = competencia_aaaamm(competencia)
    return ultimo_dia_mes(int(c[0:4]), int(c[4:6]), 0)


def format_situacao_erro(motivo: Optional[str]) -> str:
    texto = (motivo or "").strip() or MOTIVO_NAO_INFORMADO
    return f"COM ERROS ({texto})"


def _numeracao_13(raw: str) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) >= 13:
        return digits[-13:]
    return digits


def _fixo(cfg: AppConfig, key: str, default: str = "") -> str:
    return str(cfg.dados_fixos.get(key) or default).strip()


def nome_clinica_de_id(clinica_id: str) -> str:
    """Nome de exibição: clinica_id sem dígitos finais (oftalmocentro91 → oftalmocentro)."""
    return _RE_DIGITOS_FINAIS.sub("", str(clinica_id or "").strip())


def _lookup_por_nome_cod(
    nome: str,
    codigo: str,
    mapa: dict[tuple[str, str], float],
) -> Optional[float]:
    """Match exato (nome, código); fallback prefixo do nome + mesmo código."""
    if not mapa:
        return None
    nome_chave = nome_chave_prontuario(nome)
    cod_chave = codigo_procedimento_chave(codigo)
    if not nome_chave:
        return None
    valor = mapa.get((nome_chave, cod_chave))
    if valor is not None:
        return valor
    candidatos = [
        v
        for (n, c), v in mapa.items()
        if c == cod_chave and n.startswith(nome_chave)
    ]
    if not candidatos:
        return None
    distintos = {round(v, 2) for v in candidatos}
    if len(distintos) > 1:
        return None
    return candidatos[0]


def lookup_previa(
    nome: str,
    codigo: str,
    mapa_honor: dict[tuple[str, str], float],
    *,
    modalidade: str,
    numeracao: str = "",
    mapa_glaucoma: Optional[MapaPreviaGlaucoma] = None,
    valor_direto: Optional[float] = None,
) -> str:
    """Prévia: Honor($) no padrão; Valor (Total Conta) no glaucoma."""
    if modalidade == MODALIDADE_GLAUCOMA:
        if valor_direto is not None:
            return format_previa_valor(valor_direto)
        if mapa_glaucoma is not None:
            num = "".join(ch for ch in str(numeracao or "") if ch.isdigit())
            if num and num in mapa_glaucoma.por_numeracao:
                return format_previa_valor(mapa_glaucoma.por_numeracao[num])
            valor = _lookup_por_nome_cod(
                nome, codigo, mapa_glaucoma.por_nome_cod
            )
            if valor is not None:
                return format_previa_valor(valor)
        return PREVIA_PLACEHOLDER

    if modalidade != MODALIDADE_PADRAO:
        return PREVIA_PLACEHOLDER
    valor = _lookup_por_nome_cod(nome, codigo, mapa_honor)
    if valor is None:
        return PREVIA_PLACEHOLDER
    return format_previa_valor(valor)


def somar_total_cnes(rows: Sequence[RelatorioApacRow]) -> float:
    """Soma valores numéricos apenas das linhas SEM ERROS."""
    total = 0.0
    for row in rows:
        if row.situacao != SITUACAO_SEM_ERROS:
            continue
        n = parse_previa_numero(row.previa)
        if n is not None:
            total += n
    return total


def somar_total_nao_lancados(rows: Sequence[RelatorioApacRow]) -> float:
    """Soma valores numéricos das linhas COM ERROS (ausentes do TXT/SET)."""
    total = 0.0
    for row in rows:
        if row.situacao == SITUACAO_SEM_ERROS:
            continue
        n = parse_previa_numero(row.previa)
        if n is not None:
            total += n
    return total


def _meta_from_cfg(
    cfg: AppConfig,
    *,
    competencia: str,
    gerado_em: Optional[datetime] = None,
) -> RelatorioApacMeta:
    agora = gerado_em or datetime.now()
    clinica = nome_clinica_de_id(cfg.clinica_id)
    cnes = _fixo(cfg, "cnes_executante") or _fixo(cfg, "cnes_solicitante")
    return RelatorioApacMeta(
        sistema=SISTEMA_RELATORIO,
        titulo="Relatório de APAC",
        clinica=clinica,
        cnes=cnes,
        competencia=format_competencia_mm_aaaa(competencia)
        if competencia
        else "",
        gerado_em=agora.strftime("%d/%m/%Y %H:%M"),
    )


def _progress_by_id(
    records: Sequence[ProgressRecord],
) -> dict[str, ProgressRecord]:
    return {r.identidade: r for r in records}


def _codigo_digitos(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _proc_principal_glaucoma(
    pac: ParsedPaciente,
    codigo_por_numeracao: dict[str, str],
) -> Optional[ParsedProc]:
    """
    Um procedimento por paciente: coluna Código da planilha.

    Preferência: codigo_apac da fila (por numeração). Fallback SET:
    1 proc → esse; 2+ → índice 1 (ordem SET: 1º associado, Código, demais).
    """
    procs = pac.procedimentos
    if not procs:
        return None
    alvo = _codigo_digitos(codigo_por_numeracao.get(pac.numeracao, ""))
    if alvo:
        for proc in procs:
            if _codigo_digitos(proc.codigo_procedimento) == alvo:
                return proc
        # Fila tem o Código mas SET não casou — sintetiza a partir do 1º proc.
        base = procs[0]
        return ParsedProc(
            competencia=base.competencia,
            numeracao=base.numeracao,
            codigo_procedimento=codigo_por_numeracao[pac.numeracao],
            cbo=base.cbo,
            quantidade=base.quantidade or "1",
        )
    if len(procs) == 1:
        return procs[0]
    return procs[1]


def _row_from_set_pac(
    pac: ParsedPaciente,
    *,
    ref: date,
    mapa_honor: dict[tuple[str, str], float],
    modalidade: str,
    mapa_glaucoma: Optional[MapaPreviaGlaucoma] = None,
    codigo_por_numeracao: Optional[dict[str, str]] = None,
) -> list[RelatorioApacRow]:
    comp_fmt = format_competencia_mm_aaaa(pac.competencia)
    idade = idade_em(pac.nascimento, ref)
    if modalidade == MODALIDADE_GLAUCOMA:
        proc = _proc_principal_glaucoma(pac, codigo_por_numeracao or {})
        if proc is None:
            return []
        procs = (proc,)
    else:
        procs = pac.procedimentos
    out: list[RelatorioApacRow] = []
    for proc in procs:
        out.append(
            RelatorioApacRow(
                competencia=comp_fmt,
                nome=pac.nome,
                codigo_procedimento=proc.codigo_procedimento,
                quantidade=proc.quantidade or "1",
                cbo=proc.cbo,
                idade=idade,
                previa=lookup_previa(
                    pac.nome,
                    proc.codigo_procedimento,
                    mapa_honor,
                    modalidade=modalidade,
                    numeracao=pac.numeracao,
                    mapa_glaucoma=mapa_glaucoma,
                ),
                situacao=SITUACAO_SEM_ERROS,
            )
        )
    return out


def _nascimento_lanc(lanc: Lancamento) -> Optional[str]:
    if lanc.paciente is not None and lanc.paciente.nascimento:
        return lanc.paciente.nascimento
    return None


def _valor_direto_lanc(lanc: Lancamento) -> Optional[float]:
    raw = (lanc.extras or {}).get("valor_total_conta")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _row_erro_lanc(
    lanc: Lancamento,
    *,
    cfg: AppConfig,
    motivo: Optional[str],
    competencia_fallback: str,
    mapa_honor: dict[tuple[str, str], float],
    mapa_glaucoma: Optional[MapaPreviaGlaucoma] = None,
) -> RelatorioApacRow:
    raw_comp = (lanc.competencia or "").strip() or competencia_fallback
    try:
        comp_fmt = format_competencia_mm_aaaa(raw_comp)
        ref = ref_idade_competencia(raw_comp)
    except SetLayoutError:
        if competencia_fallback:
            try:
                comp_fmt = format_competencia_mm_aaaa(competencia_fallback)
                ref = ref_idade_competencia(competencia_fallback)
            except SetLayoutError:
                comp_fmt = ""
                ref = date.today()
        else:
            comp_fmt = ""
            ref = date.today()
    codigo = (lanc.codigo_apac or lanc.codigo_original or "").strip()
    if not codigo and cfg.modalidade != MODALIDADE_PADRAO:
        codigo = _fixo(cfg, "codigo_procedimento")
    cbo = _fixo(cfg, "cbo", "225265")
    qtd = _fixo(cfg, "quantidade_procedimento", "1") or "1"
    nome = (lanc.paciente_nome or "").strip()
    numeracao = (lanc.numeracao_apac or lanc.numeracao_original or "").strip()
    return RelatorioApacRow(
        competencia=comp_fmt,
        nome=nome,
        codigo_procedimento=codigo,
        quantidade=qtd,
        cbo=cbo,
        idade=idade_em(_nascimento_lanc(lanc), ref),
        previa=lookup_previa(
            nome,
            codigo,
            mapa_honor,
            modalidade=cfg.modalidade,
            numeracao=numeracao,
            mapa_glaucoma=mapa_glaucoma,
            valor_direto=_valor_direto_lanc(lanc),
        ),
        situacao=format_situacao_erro(motivo or MOTIVO_NAO_PROCESSADO),
    )


def montar_relatorio(
    cfg: AppConfig,
    parsed: ParsedSet,
    fila: Sequence[Lancamento],
    progress: Sequence[ProgressRecord],
    *,
    gerado_em: Optional[datetime] = None,
    mapa_honor: Optional[dict[tuple[str, str], float]] = None,
    mapa_glaucoma: Optional[MapaPreviaGlaucoma] = None,
) -> RelatorioApac:
    """Une SET (SEM ERROS) + lançamentos do lote ausentes do SET (COM ERROS)."""
    competencia = parsed.competencia or competencia_mes_anterior()
    meta = _meta_from_cfg(cfg, competencia=competencia, gerado_em=gerado_em)
    ref = (
        ref_idade_competencia(competencia)
        if competencia
        else date.today()
    )
    modalidade = cfg.modalidade
    if modalidade == MODALIDADE_PADRAO:
        honor = (
            mapa_honor
            if mapa_honor is not None
            else carregar_mapa_honorarios(cfg)
        )
        glauc: Optional[MapaPreviaGlaucoma] = None
    else:
        honor = mapa_honor if mapa_honor is not None else {}
        glauc = (
            mapa_glaucoma
            if mapa_glaucoma is not None
            else carregar_mapa_previa_glaucoma(cfg)
        )

    codigo_por_num: dict[str, str] = {}
    if modalidade == MODALIDADE_GLAUCOMA:
        for lanc in fila:
            num = _numeracao_13(
                lanc.numeracao_apac or lanc.numeracao_original or ""
            )
            codigo = (lanc.codigo_apac or lanc.codigo_original or "").strip()
            if num and codigo and num not in codigo_por_num:
                codigo_por_num[num] = codigo

    rows: list[RelatorioApacRow] = []
    nums_set: set[str] = set()
    for pac in parsed.pacientes:
        nums_set.add(pac.numeracao)
        rows.extend(
            _row_from_set_pac(
                pac,
                ref=ref,
                mapa_honor=honor,
                modalidade=modalidade,
                mapa_glaucoma=glauc,
                codigo_por_numeracao=codigo_por_num,
            )
        )

    by_id = _progress_by_id(progress)
    for lanc in fila:
        num = _numeracao_13(
            lanc.numeracao_apac or lanc.numeracao_original or ""
        )
        if num and num in nums_set:
            continue
        rec = by_id.get(lanc.identidade)
        motivo = rec.motivo if rec is not None else None
        if motivo is None or not str(motivo).strip():
            motivo = MOTIVO_NAO_PROCESSADO
        rows.append(
            _row_erro_lanc(
                lanc,
                cfg=cfg,
                motivo=motivo,
                competencia_fallback=competencia,
                mapa_honor=honor,
                mapa_glaucoma=glauc,
            )
        )

    return RelatorioApac(
        meta=meta,
        rows=tuple(rows),
        total_cnes=somar_total_cnes(rows),
        modalidade=modalidade,
        total_nao_lancados=somar_total_nao_lancados(rows),
    )


def montar_relatorio_de_arquivos(
    cfg: AppConfig,
    set_path: Path,
    fila: Sequence[Lancamento],
    progress: Sequence[ProgressRecord],
    *,
    gerado_em: Optional[datetime] = None,
    mapa_glaucoma: Optional[MapaPreviaGlaucoma] = None,
) -> RelatorioApac:
    parsed = parse_set_file(Path(set_path))
    return montar_relatorio(
        cfg,
        parsed,
        fila,
        progress,
        gerado_em=gerado_em,
        mapa_glaucoma=mapa_glaucoma,
    )


def _limite_fila(cfg: AppConfig) -> int:
    raw = cfg.export_set.get("limite_pacientes", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _aplicar_paciente_inicio(
    lancamentos: list[Lancamento],
    nome_alvo: str,
) -> list[Lancamento]:
    """Recorta a fila a partir de paciente_inicio (nome exato, case-insensitive)."""
    alvo = (nome_alvo or "").strip()
    if not alvo:
        return list(lancamentos)
    alvo_norm = alvo.casefold()
    idx: Optional[int] = None
    for i, lanc in enumerate(lancamentos):
        if (lanc.paciente_nome or "").strip().casefold() == alvo_norm:
            idx = i
            break
    if idx is None:
        raise SheetError(
            f"Paciente início '{alvo}' não encontrado na planilha "
            f"({len(lancamentos)} lançamento(s) ativos)."
        )
    return lancamentos[idx:]


def carregar_fila_e_progresso(
    cfg: AppConfig,
    *,
    planilha_override: Optional[Path] = None,
) -> tuple[list[Lancamento], list[ProgressRecord], Optional[MapaPreviaGlaucoma]]:
    """Fila do lote (com limite) + progresso; no glaucoma, mapa de valor numa só leitura."""
    if cfg.modalidade == MODALIDADE_GLAUCOMA:
        result = load_lancamentos(cfg, planilha_override)
        if not result.ok:
            raise SheetError(
                "Falha ao carregar planilha: " + "; ".join(result.erros[:5])
            )
        if not result.lancamentos:
            raise SheetError("Planilha sem lançamentos ativos.")
        mapa = mapa_previa_glaucoma_de_lancamentos(result.lancamentos)
        fila = _aplicar_paciente_inicio(
            list(result.lancamentos),
            str(cfg.apac.get("paciente_inicio") or ""),
        )
    else:
        fila = listar_lancamentos_a_partir(cfg, planilha_override)
        mapa = None

    lim = _limite_fila(cfg)
    if lim > 0:
        fila = fila[:lim]
    base = config_dir(cfg)
    store = ProgressStore(resolve_path(base, cfg.progresso_db))
    records = store.list_by_clinica(cfg.clinica_id)
    return fila, records, mapa


def _header_lines(meta: RelatorioApacMeta) -> list[str]:
    return [
        meta.sistema,
        meta.titulo,
        f"Clínica: {meta.clinica}",
        f"CNES: {meta.cnes}",
        f"Competência: {meta.competencia}",
        f"Gerado em: {meta.gerado_em}",
    ]


def _eh_glaucoma(relatorio: RelatorioApac) -> bool:
    return relatorio.modalidade == MODALIDADE_GLAUCOMA


def _mes_competencia_meta(competencia: str) -> str:
    """Extrai MM de meta.competencia (`MM/AAAA`); fallback `00`."""
    s = (competencia or "").strip()
    if len(s) >= 2 and s[0:2].isdigit():
        return s[0:2]
    return "00"


def nome_arquivo_relatorio_cliente(relatorio: RelatorioApac) -> str:
    """Nome sugerido no diálogo de salvar (sempre `.pdf`)."""
    if _eh_glaucoma(relatorio):
        mm = _mes_competencia_meta(relatorio.meta.competencia)
        return f"relatorio_apac_glaucoma{mm}.pdf"
    return "relatorio_apac.pdf"


def _csv_headers(relatorio: RelatorioApac) -> tuple[str, ...]:
    if _eh_glaucoma(relatorio):
        return _CSV_HEADERS_GLAUCOMA
    return _CSV_HEADERS_PADRAO


def _row_cells(row: RelatorioApacRow, *, glaucoma: bool) -> list[str]:
    if glaucoma:
        return [
            row.competencia,
            row.nome,
            row.codigo_procedimento,
            row.previa,
            row.situacao,
        ]
    return [
        row.competencia,
        row.nome,
        row.codigo_procedimento,
        row.quantidade,
        row.cbo,
        row.idade,
        row.previa,
        row.situacao,
    ]


def _linha_total_cnes(relatorio: RelatorioApac) -> str:
    return f"TOTAL: {format_moeda_br(relatorio.total_cnes)}"


def _linha_total_nao_lancados(relatorio: RelatorioApac) -> str:
    return (
        f"TOTAL NÃO LANÇADOS: {format_moeda_br(relatorio.total_nao_lancados)}"
    )


def _eh_linha_erro(row: RelatorioApacRow) -> bool:
    return row.situacao != SITUACAO_SEM_ERROS


def export_relatorio_csv(path: Path, relatorio: RelatorioApac) -> None:
    dest = Path(path)
    glaucoma = _eh_glaucoma(relatorio)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        for line in _header_lines(relatorio.meta):
            writer.writerow([line])
        writer.writerow([])
        writer.writerow(list(_csv_headers(relatorio)))
        for row in relatorio.rows:
            writer.writerow(_row_cells(row, glaucoma=glaucoma))
        writer.writerow([])
        writer.writerow([_linha_total_cnes(relatorio)])
        writer.writerow([_linha_total_nao_lancados(relatorio)])


def export_relatorio_xlsx(path: Path, relatorio: RelatorioApac) -> None:
    dest = Path(path)
    glaucoma = _eh_glaucoma(relatorio)
    n_cols = len(_csv_headers(relatorio))
    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório APAC"
    for line in _header_lines(relatorio.meta):
        ws.append([line])
    ws.append([])
    ws.append(list(_csv_headers(relatorio)))
    for row in relatorio.rows:
        ws.append(_row_cells(row, glaucoma=glaucoma))
        if _eh_linha_erro(row):
            for col in range(1, n_cols + 1):
                ws.cell(row=ws.max_row, column=col).fill = _FILL_ERRO_XLSX
    ws.append([])
    ws.append([_linha_total_cnes(relatorio)])
    ws.append([_linha_total_nao_lancados(relatorio)])
    wb.save(dest)


_PDF_COL_HEADERS_PADRAO = (
    "Competência",
    "Nome",
    "Cód. procedimento",
    "Qtd",
    "CBO",
    "Idade",
    "Valor",
    "Situação",
)
_PDF_COL_WIDTHS_PADRAO = (20, 58, 32, 12, 16, 12, 26, 72)

_PDF_COL_HEADERS_GLAUCOMA = (
    "Competência",
    "Nome",
    "Cód. procedimento",
    "Valor",
    "Situação",
)
_PDF_COL_WIDTHS_GLAUCOMA = (28, 90, 40, 36, 70)


def _unicode_font_paths() -> tuple[Path, Path]:
    """TTF regular + bold com acentos (Arial no Windows; DejaVu em Linux)."""
    import os

    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates_reg = (
        windir / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    )
    candidates_bold = (
        windir / "Fonts" / "arialbd.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    )
    regular: Optional[Path] = None
    for path in candidates_reg:
        if path.is_file():
            regular = path
            break
    if regular is None:
        raise OSError(
            "nenhuma fonte TTF Unicode encontrada (Arial/DejaVu) para o PDF"
        )
    bold = regular
    for path in candidates_bold:
        if path.is_file():
            bold = path
            break
    return regular, bold


def export_relatorio_pdf(path: Path, relatorio: RelatorioApac) -> None:
    """PDF landscape com cabeçalho SIS DG, tabela e TOTAL."""
    from fpdf import FPDF

    dest = Path(path)
    glaucoma = _eh_glaucoma(relatorio)
    headers = (
        _PDF_COL_HEADERS_GLAUCOMA if glaucoma else _PDF_COL_HEADERS_PADRAO
    )
    widths = _PDF_COL_WIDTHS_GLAUCOMA if glaucoma else _PDF_COL_WIDTHS_PADRAO

    font_reg, font_bold = _unicode_font_paths()
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.add_font("RelFont", "", str(font_reg))
    pdf.add_font("RelFont", "B", str(font_bold))

    pdf.set_font("RelFont", "B", 14)
    pdf.cell(
        0, 8, relatorio.meta.sistema, align="C", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_font("RelFont", "B", 12)
    pdf.cell(
        0, 7, relatorio.meta.titulo, align="C", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_font("RelFont", "", 10)
    for line in _header_lines(relatorio.meta)[2:]:
        pdf.cell(0, 6, line, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("RelFont", "B", 8)
    for header, width in zip(headers, widths):
        pdf.cell(width, 7, header, border=1)
    pdf.ln()

    pdf.set_font("RelFont", "", 8)
    for row in relatorio.rows:
        cells = tuple(_row_cells(row, glaucoma=glaucoma))
        if pdf.get_y() > pdf.h - 32:
            pdf.add_page()
            pdf.set_font("RelFont", "B", 8)
            for header, width in zip(headers, widths):
                pdf.cell(width, 7, header, border=1)
            pdf.ln()
            pdf.set_font("RelFont", "", 8)
        erro = _eh_linha_erro(row)
        if erro:
            pdf.set_fill_color(*_COR_ERRO_RGB)
        else:
            pdf.set_fill_color(255, 255, 255)
        for text, width in zip(cells, widths):
            s = str(text or "")
            max_chars = max(4, int(width / 1.8))
            if len(s) > max_chars:
                s = s[: max_chars - 1] + "…"
            pdf.cell(width, 6, s, border=1, fill=erro)
        pdf.ln()
        pdf.set_fill_color(255, 255, 255)

    pdf.ln(4)
    pdf.set_font("RelFont", "B", 11)
    pdf.cell(
        0,
        8,
        _linha_total_cnes(relatorio),
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(
        0,
        8,
        _linha_total_nao_lancados(relatorio),
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.output(str(dest))
