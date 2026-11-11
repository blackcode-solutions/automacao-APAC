"""
Pipeline gerar-set: planilha + BIODATA -> arquivo staging .SET (sem APAC.exe).
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Optional

from apac_bot.cid_procedimento_padrao import (
    cid_principal_por_codigo_padrao,
    classificacao_por_codigo_padrao,
)
from apac_bot.config import (
    MODALIDADE_GLAUCOMA,
    AppConfig,
    config_dir,
    fim_offset_meses,
    normalizar_modalidade_cfg,
    resolve_path,
)
from apac_bot.connectors import build_connector
from apac_bot.connectors.biodata import BiodataMappingError
from apac_bot.connectors.biodata_api import BiodataApiError
from apac_bot.icare_pacientes import IcareSheetError
from apac_bot.logging_safe import setup_logging, short_id
from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.normalize import (
    abreviar_nome_apac,
    cep_para_apac,
    identidade_paciente_set,
    nascimento_ddmmaaaa,
    sexo_para_apac,
)
from apac_bot.pipeline import (
    PipelineError,
    resolver_paciente,
    validar_dados_obrigatorios_apac,
)
from apac_bot.progress import ProgressStore, filtrar_falhas_lote, filtrar_pendentes_lote
from apac_bot.set_parse import records_from_set_file
from apac_bot.set_layout import (
    CabecalhoSet,
    CidGeralSet,
    CorpoApacSet,
    PacienteSetRecord,
    ProcedimentoSet,
    SetLayoutError,
    competencia_mes_anterior,
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
CHECKPOINT_NAME = "lote_parcial.json"
BAIRRO_PADRAO_SET = "CENTRO"
NUMERO_PADRAO_SET = "SN"

# (codigo_servico, codigo_classificacao) por procedimento — só Glaucoma.
# Códigos ausentes → ("", "") na linha 13.
GLAUCOMA_SERVICO_CLASSIFICACAO: dict[str, tuple[str, str]] = {
    "0303050012": ("131", "002"),  # acompanhamento
    "0303050187": ("", ""),
    "0301010102": ("131", "001"),  # consulta
}


def servico_classificacao_glaucoma(codigo: str) -> tuple[str, str]:
    """Retorna (serviço, classificação) para o código do procedimento Glaucoma."""
    digitos = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    return GLAUCOMA_SERVICO_CLASSIFICACAO.get(digitos, ("", ""))


def destino_in_para_modalidade(modalidade: str) -> str:
    """CBC-DST-IN: M (padrão) / E (glaucoma)."""
    return (
        "E"
        if normalizar_modalidade_cfg(modalidade) == MODALIDADE_GLAUCOMA
        else "M"
    )


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


def caminho_checkpoint(cfg: AppConfig) -> Path:
    return pasta_staging(cfg) / CHECKPOINT_NAME


def record_to_dict(rec: PacienteSetRecord) -> dict[str, Any]:
    return {
        "corpo": asdict(rec.corpo),
        "cid": asdict(rec.cid),
        "procedimentos": [asdict(p) for p in rec.procedimentos],
    }


def record_from_dict(raw: dict[str, Any]) -> PacienteSetRecord:
    return PacienteSetRecord(
        corpo=CorpoApacSet(**raw["corpo"]),
        cid=CidGeralSet(**raw["cid"]),
        procedimentos=tuple(
            ProcedimentoSet(**p) for p in (raw.get("procedimentos") or [])
        ),
    )


def salvar_checkpoint(
    cfg: AppConfig,
    *,
    competencia: str,
    records: list[PacienteSetRecord],
) -> Path:
    path = caminho_checkpoint(cfg)
    payload = {
        "incompleto": True,
        "competencia": competencia,
        "records": [record_to_dict(r) for r in records],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def carregar_checkpoint(
    cfg: AppConfig,
) -> Optional[tuple[str, list[PacienteSetRecord]]]:
    """Retorna (competencia, records) se houver lote incompleto; senão None."""
    path = caminho_checkpoint(cfg)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[gerar-set] checkpoint inválido (%s) — ignorando", exc)
        return None
    if not isinstance(raw, dict) or not raw.get("incompleto"):
        return None
    competencia = str(raw.get("competencia") or "").strip()
    items = raw.get("records")
    if not competencia or not isinstance(items, list) or not items:
        return None
    try:
        records = [record_from_dict(item) for item in items if isinstance(item, dict)]
    except (TypeError, KeyError, SetLayoutError) as exc:
        log.warning("[gerar-set] checkpoint corrompido (%s) — ignorando", exc)
        return None
    if not records:
        return None
    return competencia, records


def limpar_checkpoint(cfg: AppConfig) -> None:
    path = caminho_checkpoint(cfg)
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            log.warning("[gerar-set] falha ao remover checkpoint: %s", exc)


def _gravar_set_arquivos(
    cfg: AppConfig,
    records: list[PacienteSetRecord],
    competencia: str,
) -> Path:
    """Monta e grava o mesmo staging + nome sugerido. Retorna path do staging."""
    cab = CabecalhoSet(
        competencia=competencia,
        qtd_apac=len(records),
        smt_vrf="0000",
        orgao_origem=_export(
            cfg, "orgao_origem", "CLINICA DE SERVICOS MEDICOS GE"
        ),
        sigla=_export(cfg, "sigla", "CSMG"),
        cgc=_export(cfg, "cgc", "01192155000210"),
        orgao_destino=_export(cfg, "orgao_destino", "SECRETARIA DE SAUDE"),
        destino_in=destino_in_para_modalidade(cfg.modalidade),
        data_geracao=data_geracao_hoje(),
        versao=_export(cfg, "versao", "Versao 04.01"),
    )
    blob = montar_arquivo(cab, records)
    staging = caminho_staging(cfg)
    staging.write_bytes(blob)
    sugerido = pasta_staging(cfg) / nome_arquivo_set(competencia, cfg.modalidade)
    sugerido.write_bytes(blob)
    log.info(
        "[gerar-set] gravado staging=%s sugerido=%s pacientes=%s",
        staging,
        sugerido,
        len(records),
    )
    return staging


def lote_concluido(fila: list[Lancamento], store: ProgressStore) -> bool:
    """True se todo lançamento da fila planilha está CONCLUIDO no progresso."""
    if not fila:
        return False
    for lanc in fila:
        rec = store.get(lanc.clinica_id, lanc.identidade)
        if rec is None or rec.estado != EstadoLancamento.CONCLUIDO:
            return False
    return True


def _mesclar_record(
    records: list[PacienteSetRecord],
    novo: PacienteSetRecord,
) -> list[PacienteSetRecord]:
    """Substitui por numeração APAC ou acrescenta ao fim."""
    alvo = numeracao_13(novo.corpo.numeracao)
    out: list[PacienteSetRecord] = []
    substituiu = False
    for rec in records:
        if numeracao_13(rec.corpo.numeracao) == alvo:
            out.append(novo)
            substituiu = True
        else:
            out.append(rec)
    if not substituiu:
        out.append(novo)
    return out


def _inicializar_records(
    cfg: AppConfig,
    competencia_exec: str,
) -> tuple[str, list[PacienteSetRecord]]:
    """Checkpoint ou staging SET → lista de records; senão vazio."""
    checkpoint = carregar_checkpoint(cfg)
    if checkpoint is not None:
        comp, records = checkpoint
        records = list(records)
        if comp != competencia_exec:
            log.info(
                "[gerar-set] competência do checkpoint (%s) → %s",
                comp,
                competencia_exec,
            )
            records = _records_atualizar_competencia(
                records, competencia_exec, modalidade=cfg.modalidade
            )
        return competencia_exec, records
    staging = caminho_staging(cfg)
    if staging.is_file():
        try:
            comp, records = records_from_set_file(staging)
            records = list(records)
            if comp != competencia_exec:
                records = _records_atualizar_competencia(
                    records, competencia_exec, modalidade=cfg.modalidade
                )
            log.info(
                "[gerar-set] base carregada do staging (%s paciente(s))",
                len(records),
            )
            return competencia_exec, records
        except SetLayoutError as exc:
            log.warning("[gerar-set] staging ilegível (%s) — base vazia", exc)
    return competencia_exec, []


def _finalizar_checkpoint(
    cfg: AppConfig,
    *,
    competencia: str,
    records: list[PacienteSetRecord],
    fila_completa: list[Lancamento],
    store: ProgressStore,
) -> None:
    if lote_concluido(fila_completa, store):
        limpar_checkpoint(cfg)
    else:
        salvar_checkpoint(cfg, competencia=competencia, records=records)


def _records_atualizar_competencia(
    records: list[PacienteSetRecord],
    competencia: str,
    *,
    modalidade: str,
) -> list[PacienteSetRecord]:
    """Reaplica competência e datas do lote nos registros já montados (retomada)."""
    ini, fim = datas_competencia(
        competencia, fim_offset_meses=fim_offset_meses(modalidade)
    )
    _, fim_competencia = datas_competencia(competencia, fim_offset_meses=0)
    atualizados: list[PacienteSetRecord] = []
    for rec in records:
        corpo = replace(
            rec.corpo,
            competencia=competencia,
            data_proc=ini,
            data_ini_val=ini,
            data_fim_val=fim,
            data_obito_alta=fim_competencia,
            data_solicitacao=ini,
            data_autorizacao=ini,
        )
        cid = replace(rec.cid, competencia=competencia)
        procs = tuple(replace(p, competencia=competencia) for p in rec.procedimentos)
        atualizados.append(
            PacienteSetRecord(corpo=corpo, cid=cid, procedimentos=procs)
        )
    return atualizados


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

    ini, fim = datas_competencia(
        competencia, fim_offset_meses=fim_offset_meses(cfg.modalidade)
    )
    # Encerramento (Magnético 010082): sempre último dia do mês da competência.
    _, fim_competencia = datas_competencia(competencia, fim_offset_meses=0)
    num = numeracao_13(lanc.numeracao_original)
    cpf, cns_pac = identidade_paciente_set(pac.cpf, pac.cns)
    sexo = sexo_para_apac(pac.sexo) or ""
    nasc = nascimento_aaaammdd(
        nascimento_ddmmaaaa(pac.nascimento) or pac.nascimento
    )
    nome = abreviar_nome_apac(pac.nome or lanc.paciente_nome, 30)
    mae = abreviar_nome_apac(pac.nome_mae or "", 30)
    if not nome_mae_valido(pac.nome_mae, lanc.paciente_nome):
        raise SetLayoutError("nome_mae invalido")

    def _so_digitos(valor: object) -> str:
        return "".join(ch for ch in str(valor or "") if ch.isdigit())

    if cfg.modalidade == MODALIDADE_GLAUCOMA:
        principal = _so_digitos(lanc.codigo_apac)
        if not principal:
            raise SetLayoutError("codigo_procedimento ausente na planilha")
        associados = [
            dig
            for dig in (_so_digitos(c) for c in lanc.codigos_associados)
            if dig
        ]
        # Ordem SET: 1º associado → Código → demais associados.
        # Sem associados: só o Código. Corpo 14 usa codigos_proc[0].
        if associados:
            codigos_proc = [associados[0], principal] + associados[1:]
        else:
            codigos_proc = [principal]
        # 1 proc → 12/H400; 2+ → 15/H401
        if len(codigos_proc) >= 2:
            cid, motivo_saida = "H401", "15"
        else:
            cid, motivo_saida = "H400", "12"
    else:
        proc_cod = _so_digitos(lanc.codigo_apac)
        if not proc_cod:
            raise SetLayoutError("codigo_procedimento ausente na planilha (COD.)")
        codigos_proc = [proc_cod]
        cid = cid_principal_por_codigo_padrao(proc_cod)
        motivo_saida = "12"
    proc_cod = codigos_proc[0]

    cnes = _fixo(cfg, "cnes_executante") or _fixo(cfg, "cnes_solicitante")
    cnes_sol = _fixo(cfg, "cnes_solicitante") or cnes
    mun = _fixo(cfg, "municipio_ibge_padrao", "211230")
    sem_cpf = "N" if cpf else "S"
    tipo_atend = (
        "07"
        if cfg.modalidade == MODALIDADE_GLAUCOMA
        else _fixo(cfg, "tipo_atendimento", "00")
    )
    tipo_apac = "1" if cfg.modalidade == MODALIDADE_GLAUCOMA else "3"
    numero_bruto = (pac.numero or "").strip()
    numero_set = numero_bruto[:5] if numero_bruto else NUMERO_PADRAO_SET
    bairro_bruto = (pac.bairro or "").strip()
    bairro_set = (
        abreviar_nome_apac(bairro_bruto, 30) if bairro_bruto else BAIRRO_PADRAO_SET
    )

    corpo = CorpoApacSet(
        competencia=competencia,
        numeracao=num,
        uf_ibge=_fixo(cfg, "uf_ibge", "21"),
        cnes=cnes,
        data_proc=ini,
        data_ini_val=ini,
        data_fim_val=fim,
        tipo_atendimento=tipo_atend,
        tipo_apac=tipo_apac,
        nome=nome,
        nome_mae=mae,
        logradouro=_logradouro_limpo(pac),
        numero=numero_set,
        complemento=(pac.complemento or "")[:10],
        cep=cep_para_apac(pac.cep),
        municipio_ibge=mun,
        nascimento=nasc,
        sexo=sexo,
        medico_responsavel=_fixo(cfg, "medico_solicitante_nome"),
        codigo_procedimento=proc_cod,
        motivo_saida=motivo_saida,
        data_obito_alta=fim_competencia,
        autorizador_nome=_fixo(cfg, "autorizador_nome"),
        cns_paciente=cns_pac,
        cns_medico=_fixo(cfg, "medico_solicitante_cns"),
        cns_autorizador=_fixo(cfg, "autorizador_cns"),
        cid_causas="",
        prontuario="",
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
        bairro=bairro_set,
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
    cbo = _fixo(cfg, "cbo", "225265")
    cod_servico = _fixo(cfg, "codigo_servico", "131")
    cod_class = _fixo(cfg, "codigo_classificacao", "003")
    glaucoma = cfg.modalidade == MODALIDADE_GLAUCOMA
    procs: list[ProcedimentoSet] = []
    for cod in codigos_proc:
        if glaucoma:
            servico, classificacao = servico_classificacao_glaucoma(cod)
        else:
            servico = cod_servico
            classificacao = classificacao_por_codigo_padrao(cod, padrao=cod_class)
        procs.append(
            ProcedimentoSet(
                competencia=competencia,
                numeracao=num,
                codigo_procedimento=cod,
                cbo=cbo,
                quantidade=qtd,
                codigo_servico=servico,
                codigo_classificacao=classificacao,
            )
        )
    return PacienteSetRecord(
        corpo=corpo, cid=cid_rec, procedimentos=tuple(procs)
    )


def _persistir_parcial_apos_erro(
    cfg: AppConfig,
    records: list[PacienteSetRecord],
    competencia_lote: Optional[str],
) -> None:
    """Salva checkpoint + o mesmo SET parcial (para retomada num único arquivo)."""
    if not records or not competencia_lote:
        return
    try:
        salvar_checkpoint(cfg, competencia=competencia_lote, records=records)
        _gravar_set_arquivos(cfg, records, competencia_lote)
        log.error(
            "[gerar-set] lote incompleto salvo (%s paciente(s)) — "
            "próximo Iniciar retoma e completa o mesmo SET",
            len(records),
        )
    except SetLayoutError as exc:
        log.error("[gerar-set] falha ao gravar parcial: %s", exc)
        try:
            salvar_checkpoint(cfg, competencia=competencia_lote, records=records)
        except OSError as exc2:
            log.error("[gerar-set] falha ao salvar checkpoint: %s", exc2)
    except OSError as exc:
        log.error("[gerar-set] falha ao salvar parcial: %s", exc)


def cmd_gerar_set(
    cfg: AppConfig,
    *,
    planilha: Optional[Path] = None,
    limit: Optional[int] = None,
    somente_falhas: bool = False,
) -> int:
    """
    Consulta BIODATA e grava staging .SET (layout INTERNO).
    Retorna 0 se gerou arquivo com >=1 paciente; 1 se nenhum; 2 erro fatal.

    somente_falhas: reprocessa só ERRO + AGUARDANDO_REVISAO e mescla no SET
    existente (checkpoint ou lote_atual.SET).
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
    except (BiodataMappingError, BiodataApiError, IcareSheetError) as exc:
        log.error("[gerar-set] %s", exc)
        return 2

    store = _store(cfg)
    competencia_exec = competencia_mes_anterior()
    competencia_lote, records = _inicializar_records(cfg, competencia_exec)
    fila_completa = list(fila)
    if somente_falhas:
        fila, pulados, _alterados = filtrar_falhas_lote(fila, store)
        if not records:
            log.error(
                "[gerar-set] completar erros: sem checkpoint nem lote_atual.SET "
                "com pacientes — execute Iniciar antes"
            )
            return 2
        if not fila:
            log.error(
                "[gerar-set] completar erros: nenhum lançamento em ERRO ou "
                "AGUARDANDO_REVISAO"
            )
            return 1
        log.info(
            "[gerar-set] modo completar erros: falhas=%s pulados=%s base_set=%s",
            len(fila),
            len(pulados),
            len(records),
        )
    else:
        fila, pulados, _alterados = filtrar_pendentes_lote(fila, store)
        if pulados:
            log.info(
                "[gerar-set] pulado(s)=%s pendente(s)=%s base_set=%s",
                len(pulados),
                len(fila),
                len(records),
            )

    ok = 0
    revisao = 0
    erros = 0

    try:
        for lanc in fila:
            store.upsert(lanc, EstadoLancamento.EM_PROCESSAMENTO)
            try:
                paciente, motivo = resolver_paciente(
                    connector, lanc, origem=cfg.sistema_origem
                )
            except BiodataApiError as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.ERRO,
                    motivo=str(exc)[:300],
                )
                log.error(
                    "[gerar-set] API/rede identidade=%s: %s",
                    short_id(lanc.identidade),
                    exc,
                )
                _persistir_parcial_apos_erro(cfg, records, competencia_lote)
                return 2

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
                rec = montar_record_paciente(
                    cfg, lanc, competencia=competencia_lote
                )
                records = _mesclar_record(records, rec)
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
                # Staging ao vivo para preview/export parcial durante o lote.
                try:
                    _gravar_set_arquivos(cfg, records, competencia_lote)
                except (SetLayoutError, OSError) as exc:
                    log.warning(
                        "[gerar-set] falha ao atualizar staging parcial: %s",
                        exc,
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

    try:
        _gravar_set_arquivos(cfg, records, competencia_lote)
    except SetLayoutError as exc:
        log.error("[gerar-set] falha ao montar arquivo: %s", exc)
        _persistir_parcial_apos_erro(cfg, records, competencia_lote)
        return 2

    _finalizar_checkpoint(
        cfg,
        competencia=competencia_lote,
        records=records,
        fila_completa=fila_completa,
        store=store,
    )
    log.info(
        "[gerar-set] finalizado ok=%s revisao=%s erros=%s total_set=%s",
        ok,
        revisao,
        erros,
        len(records),
    )
    return 0 if erros == 0 else 1
