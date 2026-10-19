"""
Pipeline gerar-set: planilha + BIODATA -> arquivo staging .SET (sem APAC.exe).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, config_dir, resolve_path
from apac_bot.connectors import build_connector
from apac_bot.connectors.biodata import BiodataMappingError
from apac_bot.logging_safe import setup_logging, short_id
from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.normalize import (
    abreviar_nome_apac,
    cpf_digitos,
    nascimento_ddmmaaaa,
    sexo_para_apac,
    tem_cpf_valido,
)
from apac_bot.pipeline import (
    PipelineError,
    resolver_paciente,
    validar_dados_obrigatorios_apac,
)
from apac_bot.progress import ProgressStore
from apac_bot.set_layout import (
    CabecalhoSet,
    CidGeralSet,
    CorpoApacSet,
    PacienteSetRecord,
    ProcedimentoSet,
    SetLayoutError,
    competencia_aaaamm,
    data_geracao_hoje,
    datas_competencia,
    montar_arquivo,
    nascimento_aaaammdd,
    nome_arquivo_set,
    numeracao_13,
)
from apac_bot.sheet import SheetError, listar_lancamentos_a_partir, nome_mae_valido

log = setup_logging()

STAGING_NAME = "lote_atual.SET"


def _store(cfg: AppConfig) -> ProgressStore:
    base = config_dir(cfg)
    return ProgressStore(resolve_path(base, cfg.progresso_db))


def _fixo(cfg: AppConfig, chave: str, default: str = "") -> str:
    return str(cfg.dados_fixos.get(chave) or default).strip()


def _export(cfg: AppConfig, chave: str, default: str = "") -> str:
    return str(cfg.export_set.get(chave) or default).strip()


def pasta_staging(cfg: AppConfig) -> Path:
    base = config_dir(cfg)
    pasta = resolve_path(base, Path(_export(cfg, "pasta_saida", "data/export_set")))
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_staging(cfg: AppConfig) -> Path:
    return pasta_staging(cfg) / STAGING_NAME


def _competencia_lanc(lanc: Lancamento, fallback: str) -> str:
    raw = (lanc.competencia or "").strip()
    if raw:
        try:
            return competencia_aaaamm(raw)
        except SetLayoutError:
            digits = "".join(ch for ch in raw if ch.isdigit())
            if len(digits) >= 6:
                return digits[:6]
    if fallback:
        return competencia_aaaamm(fallback)
    raise SetLayoutError(
        f"competencia ausente para {lanc.paciente_nome!r} — "
        "preencha na planilha ou export_set.competencia_padrao"
    )


def _logradouro_limpo(pac: PacienteDados) -> str:
    logr = (pac.logradouro or pac.endereco or "").strip()
    return abreviar_nome_apac(logr, 30) if logr else ""


def montar_record_paciente(
    cfg: AppConfig,
    lanc: Lancamento,
    *,
    competencia: str,
) -> PacienteSetRecord:
    pac = lanc.paciente
    if pac is None:
        raise SetLayoutError("paciente ausente")

    motivo = validar_dados_obrigatorios_apac(pac, lanc.paciente_nome)
    if motivo:
        raise SetLayoutError(motivo)

    ini, fim = datas_competencia(competencia)
    num = numeracao_13(lanc.numeracao_original)
    cpf = cpf_digitos(pac.cpf)
    sexo = sexo_para_apac(pac.sexo) or ""
    nasc = nascimento_aaaammdd(
        nascimento_ddmmaaaa(pac.nascimento) or pac.nascimento
    )
    nome = abreviar_nome_apac(pac.nome or lanc.paciente_nome, 30)
    mae = abreviar_nome_apac(pac.nome_mae or "", 30)
    if not nome_mae_valido(pac.nome_mae, lanc.paciente_nome):
        raise SetLayoutError("nome_mae invalido")

    cid = _fixo(cfg, "cid_principal", "H250")
    proc_cod = _fixo(cfg, "codigo_procedimento") or "".join(
        ch for ch in lanc.codigo_apac if ch.isdigit()
    )
    if not proc_cod:
        raise SetLayoutError("codigo_procedimento ausente")

    cnes = _fixo(cfg, "cnes_executante") or _fixo(cfg, "cnes_solicitante")
    cnes_sol = _fixo(cfg, "cnes_solicitante") or cnes
    mun = _fixo(cfg, "municipio_ibge_padrao", "211230")
    sem_cpf = "N" if tem_cpf_valido(cpf) else "S"

    corpo = CorpoApacSet(
        competencia=competencia,
        numeracao=num,
        uf_ibge=_fixo(cfg, "uf_ibge", "21"),
        cnes=cnes,
        data_proc=ini,
        data_ini_val=ini,
        data_fim_val=fim,
        tipo_atendimento=_fixo(cfg, "tipo_atendimento", "00"),
        tipo_apac=_fixo(cfg, "tipo_apac", "3"),
        nome=nome,
        nome_mae=mae,
        logradouro=_logradouro_limpo(pac),
        numero=(pac.numero or "")[:5],
        complemento=(pac.complemento or "")[:10],
        cep="".join(ch for ch in (pac.cep or "") if ch.isdigit())[:8],
        municipio_ibge=mun,
        nascimento=nasc,
        sexo=sexo,
        medico_responsavel=_fixo(cfg, "medico_solicitante_nome"),
        codigo_procedimento=proc_cod,
        motivo_saida=_fixo(cfg, "motivo_saida", "12"),
        data_obito_alta=fim,
        autorizador_nome=_fixo(cfg, "autorizador_nome"),
        cns_paciente="".join(ch for ch in (pac.cns or "") if ch.isdigit()),
        cns_medico=_fixo(cfg, "medico_solicitante_cns"),
        cns_autorizador=_fixo(cfg, "autorizador_cns"),
        cid_causas="",
        prontuario="".join(ch for ch in str(lanc.prontuario or "") if ch.isdigit())[
            :10
        ],
        cnes_solicitante=cnes_sol,
        data_solicitacao=ini,
        data_autorizacao=ini,
        cod_orgao_emiss=_fixo(cfg, "cod_orgao_emiss", "M211130001"),
        carater_atend=_fixo(cfg, "carater_atend", "01"),
        apac_anterior="0",
        raca=_fixo(cfg, "raca", "03"),
        nome_responsavel_pac=_fixo(cfg, "nome_responsavel_padrao", "O MESMO"),
        nacionalidade=_fixo(cfg, "nacionalidade", "010"),
        etnia="",
        codigo_logradouro=_fixo(cfg, "codigo_logradouro", "008"),
        bairro=abreviar_nome_apac(pac.bairro or "", 30),
        ddd="",
        telefone="",
        email="",
        cns_executante=_fixo(cfg, "cns_executante"),
        cpf=cpf,
        ine="",
        situacao_rua="N",
        fonte_orcamentaria="",
        emendas=" ",
        sem_cpf=sem_cpf,
    )
    cid_rec = CidGeralSet(
        competencia=competencia, numeracao=num, cid_principal=cid
    )
    qtd = _fixo(cfg, "quantidade_procedimento", "1") or "1"
    proc = ProcedimentoSet(
        competencia=competencia,
        numeracao=num,
        codigo_procedimento=proc_cod,
        cbo=_fixo(cfg, "cbo", "225265"),
        quantidade=qtd,
        codigo_servico=_fixo(cfg, "codigo_servico", "131"),
        codigo_classificacao=_fixo(cfg, "codigo_classificacao", "003"),
    )
    return PacienteSetRecord(corpo=corpo, cid=cid_rec, procedimento=proc)


def cmd_gerar_set(
    cfg: AppConfig,
    *,
    planilha: Optional[Path] = None,
    limit: Optional[int] = None,
) -> int:
    """
    Consulta BIODATA e grava staging .SET (layout INTERNO).
    Retorna 0 se gerou arquivo com >=1 paciente; 1 se nenhum; 2 erro fatal.
    """
    try:
        fila = listar_lancamentos_a_partir(cfg, planilha)
    except SheetError as exc:
        log.error("[gerar-set] %s", exc)
        return 2

    lim_cfg = cfg.export_set.get("limite_pacientes", 0)
    try:
        lim = int(limit if limit is not None else lim_cfg)
    except (TypeError, ValueError):
        lim = 0
    if lim > 0:
        fila = fila[:lim]
    limite_label = lim if lim > 0 else "todos"
    log.info(
        "[gerar-set] fila=%s paciente(s) (limite=%s) a partir de %r",
        len(fila),
        limite_label,
        cfg.apac.get("paciente_inicio"),
    )

    try:
        connector = build_connector(cfg.sistema_origem, cfg)
    except BiodataMappingError as exc:
        log.error("[gerar-set] %s", exc)
        return 2

    store = _store(cfg)
    records: list[PacienteSetRecord] = []
    competencia_lote: Optional[str] = None
    ok = 0
    revisao = 0
    erros = 0

    try:
        for lanc in fila:
            store.upsert(lanc, EstadoLancamento.EM_PROCESSAMENTO)
            paciente, motivo = resolver_paciente(connector, lanc)
            if motivo:
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo=motivo,
                )
                log.warning(
                    "[gerar-set] revisao identidade=%s motivo=%s",
                    short_id(lanc.identidade),
                    motivo,
                )
                revisao += 1
                continue

            lanc.paciente = paciente
            try:
                comp = _competencia_lanc(
                    lanc, _export(cfg, "competencia_padrao", "")
                )
                if competencia_lote is None:
                    competencia_lote = comp
                rec = montar_record_paciente(cfg, lanc, competencia=comp)
                records.append(rec)
                store.upsert(
                    lanc,
                    EstadoLancamento.CONCLUIDO,
                    motivo="incluido no SET",
                )
                ok += 1
                log.info(
                    "[gerar-set] OK %s numeracao=%s",
                    short_id(lanc.identidade),
                    lanc.numeracao_original,
                )
            except SetLayoutError as exc:
                store.upsert(lanc, EstadoLancamento.ERRO, motivo=str(exc))
                log.error(
                    "[gerar-set] layout identidade=%s: %s",
                    short_id(lanc.identidade),
                    exc,
                )
                erros += 1
            except Exception as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.ERRO,
                    motivo=type(exc).__name__,
                )
                log.error(
                    "[gerar-set] erro identidade=%s tipo=%s",
                    short_id(lanc.identidade),
                    type(exc).__name__,
                )
                erros += 1
    finally:
        connector.close()

    if not records or not competencia_lote:
        log.error(
            "[gerar-set] nenhum paciente montado (ok=%s revisao=%s erros=%s)",
            ok,
            revisao,
            erros,
        )
        return 1

    cab = CabecalhoSet(
        competencia=competencia_lote,
        qtd_apac=len(records),
        smt_vrf="0000",
        orgao_origem=_export(
            cfg, "orgao_origem", "CLINICA DE SERVICOS MEDICOS GE"
        ),
        sigla=_export(cfg, "sigla", "CSMG"),
        cgc=_export(cfg, "cgc", "01192155000210"),
        orgao_destino=_export(cfg, "orgao_destino", "SECRETARIA DE SAUDE"),
        destino_in=_export(cfg, "destino_in", "M"),
        data_geracao=data_geracao_hoje(),
        versao=_export(cfg, "versao", "Versao 04.01"),
    )
    try:
        blob = montar_arquivo(cab, records)
    except SetLayoutError as exc:
        log.error("[gerar-set] falha ao montar arquivo: %s", exc)
        return 2

    staging = caminho_staging(cfg)
    staging.write_bytes(blob)
    sugerido = pasta_staging(cfg) / nome_arquivo_set(
        competencia_lote, _export(cfg, "prefixo_arquivo", "APOFTAL") or "APOFTAL"
    )
    sugerido.write_bytes(blob)
    log.info(
        "[gerar-set] gravado staging=%s sugerido=%s pacientes=%s",
        staging,
        sugerido,
        len(records),
    )
    log.info(
        "[gerar-set] finalizado ok=%s revisao=%s erros=%s",
        ok,
        revisao,
        erros,
    )
    return 0 if erros == 0 else 1
