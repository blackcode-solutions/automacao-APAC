"""Relatório APAC para cliente: merge SET × lote × progresso e exports."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

from apac_bot.config import MODALIDADE_GLAUCOMA, AppConfig
from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.progress import ProgressRecord
from apac_bot.relatorio_apac import (
    PREVIA_PLACEHOLDER,
    SISTEMA_RELATORIO,
    SITUACAO_SEM_ERROS,
    export_relatorio_csv,
    export_relatorio_pdf,
    export_relatorio_xlsx,
    format_moeda_br,
    format_situacao_erro,
    idade_em,
    lookup_previa,
    montar_relatorio,
    nome_arquivo_relatorio_cliente,
    nome_clinica_de_id,
    somar_total_cnes,
    somar_total_nao_lancados,
)
from apac_bot.set_parse import (
    ParsedPaciente,
    ParsedProc,
    ParsedSet,
    parse_set_file,
)
from apac_bot.sheet import (
    MapaPreviaGlaucoma,
    carregar_mapa_honorarios,
    carregar_mapa_previa_glaucoma,
    codigo_procedimento_chave,
    load_lancamentos,
    mapa_previa_glaucoma_de_lancamentos,
)

FIXTURE = Path(__file__).parent / "fixtures" / "APOFTAL9.txt"


def _cfg(
    *,
    modalidade: str = "padrao",
    honor_path: Path | None = None,
    planilha_path: Path | None = None,
) -> AppConfig:
    raw: dict = {
        "clinica_id": "oftalmocentro91",
        "apac": {"modalidade": modalidade},
        "dados_fixos": {
            "cnes_solicitante": "6618839",
            "cnes_executante": "6618839",
            "codigo_procedimento": "0405050372",
            "cbo": "225265",
            "quantidade_procedimento": "1",
        },
        "export_set": {
            "orgao_origem": "CLINICA DE SERVICOS MEDICOS GE",
        },
    }
    if honor_path is not None:
        raw["planilha_prontuarios"] = {
            "caminho": str(honor_path),
            "aba": "APAC ",
            "linha_cabecalho": 3,
            "colunas": {
                "PRONTUARIO": "Prontuário",
                "CLIENTE": "Cliente",
                "CODIGO": "Código",
                "HONOR": "Honor($)",
                "QTD": "Qtd",
            },
        }
    if planilha_path is not None:
        raw["planilha"] = {
            "caminho": str(planilha_path),
            "aba": "PRODUÇÃO",
            "colunas": {
                "NUMERACAO": "Numeração",
                "CODIGO": "Código",
                "AUDITOR": "Auditor",
                "PACIENTE": "Paciente",
            },
        }
    return AppConfig(raw=raw, path=Path("config.json"))


def _glaucoma_xlsx(tmp_path: Path) -> Path:
    """Planilha mínima glaucoma com Valor (Total Conta) alinhada ao fixture SET."""
    path = tmp_path / "cenario_glaucoma.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Base Consultas"
    ws.append(
        [
            "Prontuário",
            "Nº Atend.",
            "Cliente",
            "Data",
            "Código",
            "Procedimento",
            "Valor (Total Conta)",
            "Associado a",
            "Chave (Guia)",
        ]
    )
    ws.append(
        [
            "1",
            "1",
            "CLERIVAN ANDRADE DE ARAUJO",
            "01/09/2026",
            "0405050372",
            "Consulta",
            112.77,
            "",
            "212620540921-8",
        ]
    )
    ws.append(
        [
            "2",
            "2",
            "MARIA DE JESUS COSTA",
            "01/09/2026",
            "0405050372",
            "Consulta",
            50.0,
            "",
            "212620540922-9",
        ]
    )
    ws.append(
        [
            "3",
            "3",
            "CLAUDIA MARQUILENE SILVA CUTRIM",
            "01/09/2026",
            "0405050372",
            "Consulta",
            771.6,
            "",
            "212699999999-9",
        ]
    )
    wb.save(path)
    return path


def _lanc(
    numeracao: str,
    nome: str,
    *,
    nascimento: str | None = None,
    motivo_estado: EstadoLancamento = EstadoLancamento.ERRO,
) -> Lancamento:
    pac = None
    if nascimento is not None:
        pac = PacienteDados(nascimento=nascimento, nome=nome)
    return Lancamento(
        clinica_id="oftalmocentro91",
        numeracao_original=numeracao,
        numeracao_apac=numeracao,
        codigo_original="0405050372",
        codigo_apac="0405050372",
        auditor="A",
        paciente_nome=nome,
        competencia="202609",
        paciente=pac,
        estado=motivo_estado,
    )


def _rec(lanc: Lancamento, motivo: str) -> ProgressRecord:
    return ProgressRecord(
        clinica_id=lanc.clinica_id,
        identidade=lanc.identidade,
        numeracao_original=lanc.numeracao_original,
        estado=EstadoLancamento.ERRO,
        hash_entrada=lanc.hash_entrada(),
        motivo=motivo,
        precisa_reconciliar=False,
        atualizado_em="2026-09-15T12:00:00+00:00",
    )


def _honor_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "prontuarios.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "APAC "
    ws.append(["titulo"])
    ws.append(["periodo"])
    ws.append(
        [
            "Prontuário",
            "Cliente",
            "Data",
            "Cód./Convênio",
            "Código",
            "Procedimento",
            "Profissional",
            "Qtd",
            "Honor($)",
        ]
    )
    ws.append(
        [
            1,
            "CLERIVAN ANDRADE DE ARAUJO",
            None,
            "SUS",
            405050372,
            "PROC",
            "MED",
            1,
            112.77,
        ]
    )
    ws.append(
        [
            2,
            "MARIA DE JESUS COSTA",
            None,
            "SUS",
            "0405050372",
            "PROC",
            "MED",
            1,
            50.0,
        ]
    )
    wb.save(path)
    return path


def test_idade_ultimo_dia_competencia():
    assert idade_em("19811027", date(2026, 9, 30)) == "44"
    assert idade_em("19811027", date(2026, 10, 27)) == "45"
    assert idade_em(None, date(2026, 9, 30)) == PREVIA_PLACEHOLDER
    assert idade_em("19/12/1967", date(2026, 9, 30)) == "58"


def test_format_situacao_erro():
    assert format_situacao_erro("cpf invalido") == "COM ERROS (cpf invalido)"
    assert "motivo não informado" in format_situacao_erro("")
    assert "motivo não informado" in format_situacao_erro(None)


def test_nome_clinica_de_id():
    assert nome_clinica_de_id("oftalmocentro91") == "oftalmocentro"
    assert nome_clinica_de_id("abc123") == "abc"
    assert nome_clinica_de_id("clinica") == "clinica"
    assert nome_clinica_de_id("  x9  ") == "x"


def test_codigo_procedimento_chave():
    assert codigo_procedimento_chave("0405050372") == "405050372"
    assert codigo_procedimento_chave(405050372) == "405050372"


def test_lookup_previa_padrao_e_glaucoma():
    mapa = {("clerivan andrade de araujo", "405050372"): 112.77}
    assert (
        lookup_previa(
            "CLERIVAN ANDRADE DE ARAUJO",
            "0405050372",
            mapa,
            modalidade="padrao",
        )
        == format_moeda_br(112.77)
    )
    assert (
        lookup_previa(
            "CLERIVAN ANDRADE DE ARAUJO",
            "0405050372",
            mapa,
            modalidade=MODALIDADE_GLAUCOMA,
        )
        == PREVIA_PLACEHOLDER
    )
    glauc = MapaPreviaGlaucoma(
        por_nome_cod={("clerivan andrade de araujo", "405050372"): 98.04},
        por_numeracao={"2126205409218": 98.04},
    )
    assert (
        lookup_previa(
            "CLERIVAN ANDRADE DE ARAUJO",
            "0405050372",
            {},
            modalidade=MODALIDADE_GLAUCOMA,
            mapa_glaucoma=glauc,
        )
        == format_moeda_br(98.04)
    )
    assert (
        lookup_previa(
            "NOME DIFERENTE",
            "0405050372",
            {},
            modalidade=MODALIDADE_GLAUCOMA,
            numeracao="2126205409218",
            mapa_glaucoma=glauc,
        )
        == format_moeda_br(98.04)
    )


def test_lookup_previa_nome_truncado_set():
    """SET corta em 30 chars; planilha tem nome completo."""
    mapa = {("claudia marquilene silva cutrim", "405050372"): 771.6}
    assert (
        lookup_previa(
            "CLAUDIA MARQUILENE SILVA C",
            "0405050372",
            mapa,
            modalidade="padrao",
        )
        == format_moeda_br(771.6)
    )


def test_lookup_previa_truncado_ambiguo_valores_diferentes():
    mapa = {
        ("maria da conceicao ferreira rodrigues", "405050372"): 100.0,
        ("maria da conceicao ferreira ramos", "405050372"): 200.0,
    }
    assert (
        lookup_previa(
            "MARIA DA CONCEICAO FERREIRA R",
            "0405050372",
            mapa,
            modalidade="padrao",
        )
        == PREVIA_PLACEHOLDER
    )


def test_lookup_previa_exato_preferido_sobre_prefixo():
    mapa = {
        ("claudia marquilene silva c", "405050372"): 10.0,
        ("claudia marquilene silva cutrim", "405050372"): 771.6,
    }
    assert (
        lookup_previa(
            "CLAUDIA MARQUILENE SILVA C",
            "0405050372",
            mapa,
            modalidade="padrao",
        )
        == format_moeda_br(10.0)
    )


def test_carregar_mapa_honorarios(tmp_path: Path):
    path = _honor_xlsx(tmp_path)
    cfg = _cfg(honor_path=path)
    mapa = carregar_mapa_honorarios(cfg)
    assert mapa[("clerivan andrade de araujo", "405050372")] == 112.77
    assert mapa[("maria de jesus costa", "405050372")] == 50.0


def test_montar_com_previa_e_total(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    cfg = _cfg(honor_path=_honor_xlsx(tmp_path))
    falha = _lanc("2126999999999", "PACIENTE FALHA", nascimento="01/01/1980")
    rel = montar_relatorio(
        cfg,
        parsed,
        [falha],
        [_rec(falha, "faltam: cpf/cns")],
        gerado_em=datetime(2026, 10, 23, 10, 0),
    )
    sem = [r for r in rel.rows if r.situacao == SITUACAO_SEM_ERROS]
    assert sem[0].quantidade == "1"
    assert sem[0].previa == format_moeda_br(112.77)
    # 2º paciente do fixture com match 50.0; 3º sem match → —
    assert sem[1].previa == format_moeda_br(50.0)
    assert sem[2].previa == PREVIA_PLACEHOLDER
    # TOTAL só SEM ERROS com valor
    assert abs(rel.total_cnes - (112.77 + 50.0)) < 0.001
    assert abs(somar_total_cnes(rel.rows) - rel.total_cnes) < 0.001
    com = [r for r in rel.rows if r.situacao.startswith("COM ERROS")]
    assert com[0].quantidade == "1"


def test_glaucoma_previa_placeholder_sem_mapa(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    cfg = _cfg(modalidade=MODALIDADE_GLAUCOMA, honor_path=_honor_xlsx(tmp_path))
    rel = montar_relatorio(
        cfg,
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_glaucoma=MapaPreviaGlaucoma(por_nome_cod={}, por_numeracao={}),
    )
    assert rel.modalidade == MODALIDADE_GLAUCOMA
    assert all(r.previa == PREVIA_PLACEHOLDER for r in rel.rows)
    assert rel.total_cnes == 0.0


def test_carregar_mapa_previa_glaucoma(tmp_path: Path):
    path = _glaucoma_xlsx(tmp_path)
    cfg = _cfg(modalidade=MODALIDADE_GLAUCOMA, planilha_path=path)
    mapa = carregar_mapa_previa_glaucoma(cfg)
    assert mapa.por_nome_cod[("clerivan andrade de araujo", "405050372")] == 112.77
    assert mapa.por_numeracao["2126205409218"] == 112.77
    assert mapa.por_numeracao["2126205409229"] == 50.0


def test_mapa_previa_glaucoma_de_lancamentos_equivale_arquivo(tmp_path: Path):
    path = _glaucoma_xlsx(tmp_path)
    cfg = _cfg(modalidade=MODALIDADE_GLAUCOMA, planilha_path=path)
    do_arquivo = carregar_mapa_previa_glaucoma(cfg)
    result = load_lancamentos(cfg)
    assert result.ok
    da_fila = mapa_previa_glaucoma_de_lancamentos(result.lancamentos)
    assert da_fila.por_nome_cod == do_arquivo.por_nome_cod
    assert da_fila.por_numeracao == do_arquivo.por_numeracao


def test_montar_glaucoma_previa_e_total(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    cfg = _cfg(
        modalidade=MODALIDADE_GLAUCOMA,
        planilha_path=_glaucoma_xlsx(tmp_path),
    )
    falha = _lanc("2126999999999", "PACIENTE FALHA", nascimento="01/01/1980")
    falha.extras = {"valor_total_conta": 33.0}
    rel = montar_relatorio(
        cfg,
        parsed,
        [falha],
        [_rec(falha, "faltam: cpf/cns")],
        gerado_em=datetime(2026, 10, 23, 10, 0),
    )
    assert rel.modalidade == MODALIDADE_GLAUCOMA
    sem = [r for r in rel.rows if r.situacao == SITUACAO_SEM_ERROS]
    assert sem[0].previa == format_moeda_br(112.77)
    assert sem[1].previa == format_moeda_br(50.0)
    assert sem[2].previa == PREVIA_PLACEHOLDER
    assert abs(rel.total_cnes - (112.77 + 50.0)) < 0.001
    com = [r for r in rel.rows if r.situacao.startswith("COM ERROS")]
    assert com[0].previa == format_moeda_br(33.0)
    # TOTAL só SEM ERROS — COM ERROS não entra
    assert abs(somar_total_cnes(rel.rows) - rel.total_cnes) < 0.001
    assert abs(rel.total_nao_lancados - 33.0) < 0.001
    assert abs(somar_total_nao_lancados(rel.rows) - 33.0) < 0.001


def test_glaucoma_relatorio_so_codigo_coluna_nao_associados():
    """SET com associados (ordem 1º assoc → Código → demais); relatório 1 linha."""
    proc_assoc = ParsedProc(
        competencia="202609",
        numeracao="2126205409218",
        codigo_procedimento="0303050187",
        cbo="225265",
        quantidade="1",
    )
    proc_codigo = ParsedProc(
        competencia="202609",
        numeracao="2126205409218",
        codigo_procedimento="0303050160",
        cbo="225265",
        quantidade="1",
    )
    proc_assoc2 = ParsedProc(
        competencia="202609",
        numeracao="2126205409218",
        codigo_procedimento="0303050195",
        cbo="225265",
        quantidade="1",
    )
    pac = ParsedPaciente(
        competencia="202609",
        numeracao="2126205409218",
        nome="CLERIVAN ANDRADE DE ARAUJO",
        nascimento="19811027",
        procedimentos=(proc_assoc, proc_codigo, proc_assoc2),
    )
    parsed = ParsedSet(
        competencia="202609",
        orgao_origem="TESTE",
        pacientes=(pac,),
    )
    lanc = _lanc("2126205409218", "CLERIVAN ANDRADE DE ARAUJO")
    lanc.codigo_original = "0303050160"
    lanc.codigo_apac = "0303050160"
    glauc = MapaPreviaGlaucoma(
        por_nome_cod={},
        por_numeracao={"2126205409218": 98.04},
    )
    rel = montar_relatorio(
        _cfg(modalidade=MODALIDADE_GLAUCOMA),
        parsed,
        [lanc],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_glaucoma=glauc,
    )
    sem = [r for r in rel.rows if r.situacao == SITUACAO_SEM_ERROS]
    assert len(sem) == 1
    assert sem[0].codigo_procedimento == "0303050160"
    assert sem[0].previa == format_moeda_br(98.04)
    assert abs(rel.total_cnes - 98.04) < 0.001


def test_padrao_relatorio_mantem_multiplos_procs():
    """Regressão: modalidade padrão ainda expande todos os procedimentos do SET."""
    p1 = ParsedProc(
        competencia="202609",
        numeracao="2126205409218",
        codigo_procedimento="0405050372",
        cbo="225265",
        quantidade="1",
    )
    p2 = ParsedProc(
        competencia="202609",
        numeracao="2126205409218",
        codigo_procedimento="0405050999",
        cbo="225265",
        quantidade="1",
    )
    pac = ParsedPaciente(
        competencia="202609",
        numeracao="2126205409218",
        nome="CLERIVAN ANDRADE DE ARAUJO",
        nascimento="19811027",
        procedimentos=(p1, p2),
    )
    parsed = ParsedSet(
        competencia="202609",
        orgao_origem="TESTE",
        pacientes=(pac,),
    )
    rel = montar_relatorio(
        _cfg(),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )
    sem = [r for r in rel.rows if r.situacao == SITUACAO_SEM_ERROS]
    assert len(sem) == 2
    assert {r.codigo_procedimento for r in sem} == {
        "0405050372",
        "0405050999",
    }


def test_glaucoma_nome_truncado_por_prefixo_ou_guia():
    glauc = MapaPreviaGlaucoma(
        por_nome_cod={
            ("claudia marquilene silva cutrim", "405050372"): 771.6,
        },
        por_numeracao={"2126205409218": 112.77},
    )
    assert (
        lookup_previa(
            "CLAUDIA MARQUILENE SILVA C",
            "0405050372",
            {},
            modalidade=MODALIDADE_GLAUCOMA,
            mapa_glaucoma=glauc,
        )
        == format_moeda_br(771.6)
    )
    assert (
        lookup_previa(
            "CLAUDIA MARQUILENE SILVA C",
            "9999999999",
            {},
            modalidade=MODALIDADE_GLAUCOMA,
            numeracao="2126205409218",
            mapa_glaucoma=glauc,
        )
        == format_moeda_br(112.77)
    )


def test_export_glaucoma_sem_qtd_cbo_idade(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    glauc = MapaPreviaGlaucoma(
        por_nome_cod={("clerivan andrade de araujo", "405050372"): 10.0},
        por_numeracao={},
    )
    rel = montar_relatorio(
        _cfg(modalidade=MODALIDADE_GLAUCOMA),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_glaucoma=glauc,
    )

    csv_path = tmp_path / "relatorio_glaucoma.csv"
    export_relatorio_csv(csv_path, rel)
    text = csv_path.read_text(encoding="utf-8-sig")
    assert (
        "competencia,nome,codigo_procedimento,valor,situacao" in text
    )
    assert "quantidade" not in text.splitlines()[7]
    assert ",cbo," not in text
    assert ",idade," not in text
    assert "TOTAL:" in text
    assert "TOTAL NÃO LANÇADOS:" in text
    assert "TOTAL DO CNES" not in text
    assert format_moeda_br(10.0) in text

    xlsx_path = tmp_path / "relatorio_glaucoma.xlsx"
    export_relatorio_xlsx(xlsx_path, rel)
    wb = load_workbook(xlsx_path)
    ws = wb.active
    assert ws["A8"].value == "competencia"
    assert ws["D8"].value == "valor"
    assert ws["E8"].value == "situacao"
    assert ws["F8"].value is None

    pdf_path = tmp_path / "relatorio_glaucoma.pdf"
    export_relatorio_pdf(pdf_path, rel)
    assert pdf_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_export_total_nao_lancados(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    falha = _lanc("2126999999999", "PACIENTE FALHA", nascimento="01/01/1980")
    falha.extras = {"valor_total_conta": 33.0}
    rel = montar_relatorio(
        _cfg(modalidade=MODALIDADE_GLAUCOMA),
        parsed,
        [falha],
        [_rec(falha, "faltam: cpf/cns")],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_glaucoma=MapaPreviaGlaucoma(por_nome_cod={}, por_numeracao={}),
    )
    assert abs(rel.total_nao_lancados - 33.0) < 0.001
    assert rel.total_cnes == 0.0

    csv_path = tmp_path / "nao_lancados.csv"
    export_relatorio_csv(csv_path, rel)
    text = csv_path.read_text(encoding="utf-8-sig")
    assert f"TOTAL: {format_moeda_br(0.0)}" in text
    assert f"TOTAL NÃO LANÇADOS: {format_moeda_br(33.0)}" in text


def test_montar_sem_erros_e_com_erros():
    parsed = parse_set_file(FIXTURE)
    ok = _lanc("2126205409218", "CLERIVAN ANDRADE DE ARAUJO")
    falha = _lanc(
        "2126999999999",
        "PACIENTE FALHA",
        nascimento="01/01/1980",
    )
    fila = [ok, falha]
    progress = [_rec(falha, "faltam: cpf/cns")]

    rel = montar_relatorio(
        _cfg(),
        parsed,
        fila,
        progress,
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )

    assert rel.meta.sistema == SISTEMA_RELATORIO
    assert rel.meta.clinica == "oftalmocentro"
    assert len(rel.rows) == 4
    sem = [r for r in rel.rows if r.situacao == SITUACAO_SEM_ERROS]
    com = [r for r in rel.rows if r.situacao.startswith("COM ERROS")]
    assert len(sem) == 3
    assert len(com) == 1
    assert sem[0].quantidade == "1"
    assert com[0].nome == "PACIENTE FALHA"


def test_export_csv_e_xlsx(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    rel = montar_relatorio(
        _cfg(),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={("clerivan andrade de araujo", "405050372"): 10.0},
    )

    csv_path = tmp_path / "relatorio.csv"
    export_relatorio_csv(csv_path, rel)
    text = csv_path.read_text(encoding="utf-8-sig")
    assert (
        "competencia,nome,codigo_procedimento,quantidade,cbo,idade,valor,situacao"
        in text
    )
    assert "TOTAL:" in text
    assert "TOTAL NÃO LANÇADOS:" in text
    assert "TOTAL DO CNES" not in text
    assert format_moeda_br(10.0) in text

    xlsx_path = tmp_path / "relatorio.xlsx"
    export_relatorio_xlsx(xlsx_path, rel)
    wb = load_workbook(xlsx_path)
    ws = wb.active
    assert ws["A1"].value == SISTEMA_RELATORIO
    assert ws["A8"].value == "competencia"
    assert ws["D8"].value == "quantidade"
    assert ws["G8"].value == "valor"
    assert ws["B9"].value == "CLERIVAN ANDRADE DE ARAUJO"


def test_nome_arquivo_relatorio_cliente():
    parsed = parse_set_file(FIXTURE)
    rel_padrao = montar_relatorio(
        _cfg(),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )
    assert nome_arquivo_relatorio_cliente(rel_padrao) == "relatorio_apac.pdf"
    assert rel_padrao.meta.competencia == "09/2026"

    rel_glauc = montar_relatorio(
        _cfg(modalidade=MODALIDADE_GLAUCOMA),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_glaucoma=MapaPreviaGlaucoma(por_nome_cod={}, por_numeracao={}),
    )
    assert (
        nome_arquivo_relatorio_cliente(rel_glauc)
        == "relatorio_apac_glaucoma09.pdf"
    )


def test_export_pdf_smoke(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    rel = montar_relatorio(
        _cfg(),
        parsed,
        [],
        [],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )
    pdf_path = tmp_path / "relatorio.pdf"
    export_relatorio_pdf(pdf_path, rel)
    assert pdf_path.is_file()
    data = pdf_path.read_bytes()
    assert len(data) > 500
    assert data.startswith(b"%PDF")
    assert b"841.89" in data


def test_export_xlsx_linha_erro_vermelha(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    falha = _lanc("2126999999999", "PACIENTE FALHA", nascimento="01/01/1980")
    rel = montar_relatorio(
        _cfg(),
        parsed,
        [falha],
        [_rec(falha, "faltam: cpf/cns")],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )
    xlsx_path = tmp_path / "relatorio_erro.xlsx"
    export_relatorio_xlsx(xlsx_path, rel)
    wb = load_workbook(xlsx_path)
    ws = wb.active
    # Header na linha 8; dados SEM ERROS 9..; COM ERROS na última linha de dados
    row_ok = 9
    assert ws.cell(row=row_ok, column=1).fill.fgColor is None or (
        ws.cell(row=row_ok, column=1).fill.fgColor.rgb
        in (None, "00000000", "0")
        or ws.cell(row=row_ok, column=1).fill.fill_type is None
    )
    row_erro = None
    for r in range(9, ws.max_row + 1):
        situacao = ws.cell(row=r, column=8).value
        if situacao and str(situacao).startswith("COM ERROS"):
            row_erro = r
            break
    assert row_erro is not None
    fill = ws.cell(row=row_erro, column=1).fill
    assert fill.fill_type == "solid"
    assert fill.fgColor.rgb in ("00FFCCCC", "FFCCCC")
    for col in range(1, 9):
        assert ws.cell(row=row_erro, column=col).fill.fgColor.rgb in (
            "00FFCCCC",
            "FFCCCC",
        )


def test_export_pdf_com_linha_erro_smoke(tmp_path: Path):
    parsed = parse_set_file(FIXTURE)
    falha = _lanc("2126999999999", "PACIENTE FALHA", nascimento="01/01/1980")
    rel = montar_relatorio(
        _cfg(),
        parsed,
        [falha],
        [_rec(falha, "faltam: cpf/cns")],
        gerado_em=datetime(2026, 10, 23, 10, 0),
        mapa_honor={},
    )
    pdf_path = tmp_path / "relatorio_erro.pdf"
    export_relatorio_pdf(pdf_path, rel)
    assert pdf_path.is_file()
    data = pdf_path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 500
