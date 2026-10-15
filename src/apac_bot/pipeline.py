from __future__ import annotations

from pathlib import Path
from typing import Optional

from apac_bot.apac import ApacAutomator, ApacBlockedError, ApacInterruptedError
from apac_bot.config import AppConfig, config_dir, resolve_path, validate_config
from apac_bot.connectors import build_connector
from apac_bot.connectors.biodata import BiodataMappingError
from apac_bot.logging_safe import setup_logging, short_id
from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.normalize import nascimento_ddmmaaaa, sexo_para_apac, tem_cpf_valido
from apac_bot.progress import ProgressStore
from apac_bot.sheet import SheetError, load_lancamentos, nome_mae_valido

log = setup_logging()


class PipelineError(Exception):
    pass


def validar_dados_obrigatorios_apac(
    paciente: Optional[PacienteDados],
    paciente_nome: str,
) -> Optional[str]:
    """
    Pré-check antes do Insert no Magnético.
    Retorna None se CPF, nome da mãe, nascimento e sexo estiverem ok;
    senão string com os campos faltando (ex.: "faltam: cpf, nome_mae").
    """
    if paciente is None:
        return "faltam: cpf, nome_mae, nascimento, sexo"

    faltam: list[str] = []
    if not tem_cpf_valido(paciente.cpf):
        faltam.append("cpf")
    if not nome_mae_valido(paciente.nome_mae, paciente_nome):
        faltam.append("nome_mae")
    if not nascimento_ddmmaaaa(paciente.nascimento):
        faltam.append("nascimento")
    if not sexo_para_apac(paciente.sexo):
        faltam.append("sexo")
    if not faltam:
        return None
    return "faltam: " + ", ".join(faltam)


def _store(cfg: AppConfig) -> ProgressStore:
    base = config_dir(cfg)
    return ProgressStore(resolve_path(base, cfg.progresso_db))


def validate_all(cfg: AppConfig, planilha: Optional[Path] = None) -> list[Lancamento]:
    avisos = validate_config(cfg, for_live=False)
    for a in avisos:
        log.warning(a)
    result = load_lancamentos(cfg, planilha)
    for a in result.avisos:
        log.warning(a)
    if result.erros:
        for e in result.erros:
            log.error(e)
        raise PipelineError(f"Validação da planilha falhou ({len(result.erros)} erro(s)).")
    log.info("Planilha OK: %s lançamento(s).", len(result.lancamentos))
    return result.lancamentos


def resolver_paciente(connector, lanc: Lancamento) -> tuple[Optional[PacienteDados], Optional[str]]:
    """
    Ordem:
      1) prontuario (2a planilha) — busca pelo numero no dialogo
      2) id_paciente
      3) nome (+ desambiguacao CPF / prontuario)
    Retorna (paciente|None, motivo_revisao|None).
    """
    pront = "".join(ch for ch in str(lanc.prontuario or "") if ch.isdigit())
    if pront:
        log.info("Buscando BIODATA por prontuario=%s", pront)
        buscar_pront = getattr(connector, "buscar_por_prontuario", None)
        encontrado = (
            buscar_pront(pront)
            if callable(buscar_pront)
            else connector.buscar_por_id(pront)
        )
        if encontrado is not None:
            return encontrado, None
        log.warning(
            "Prontuario %s nao encontrado — fallback busca por nome (%s).",
            pront,
            lanc.paciente_nome,
        )

    if lanc.id_paciente:
        encontrado = connector.buscar_por_id(lanc.id_paciente)
        if encontrado is None:
            return None, "id_paciente não encontrado na origem"
        return encontrado, None

    candidatos = connector.buscar_por_nome(
        lanc.paciente_nome,
        prontuario=lanc.prontuario,
    )
    if not candidatos:
        return None, "nome não encontrado na origem"
    if len(candidatos) == 1:
        return candidatos[0], None

    # Filtro extra se o connector nao desambiguou (ex.: mock sem digitos no id)
    if pront:
        por_pront = [
            p
            for p in candidatos
            if p.id_paciente
            and "".join(ch for ch in p.id_paciente if ch.isdigit()) == pront
        ]
        if len(por_pront) == 1:
            log.info(
                "Desambiguação por prontuario %s — 1 de %s candidato(s).",
                pront,
                len(candidatos),
            )
            return por_pront[0], None

    com_cpf = [p for p in candidatos if tem_cpf_valido(p.cpf)]
    if len(com_cpf) == 1:
        log.info(
            "Desambiguação por CPF: 1 de %s candidato(s) tem CPF — usando esse.",
            len(candidatos),
        )
        return com_cpf[0], None
    if len(com_cpf) >= 2:
        return (
            None,
            f"busca por nome ambígua ({len(com_cpf)} com CPF / {len(candidatos)} resultados)",
        )
    return (
        None,
        f"busca por nome ambígua ({len(candidatos)} resultados, nenhum com CPF)",
    )


def cmd_fetch(
    cfg: AppConfig,
    *,
    planilha: Optional[Path] = None,
    limit: Optional[int] = None,
) -> int:
    lancamentos = validate_all(cfg, planilha)
    if limit is not None:
        lancamentos = lancamentos[:limit]

    try:
        connector = build_connector(cfg.sistema_origem, cfg)
    except BiodataMappingError as exc:
        log.error("%s", exc)
        return 2

    store = _store(cfg)
    ok = 0
    revisao = 0
    erros = 0
    try:
        for lanc in lancamentos:
            paciente, motivo = resolver_paciente(connector, lanc)
            if motivo:
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo=motivo,
                )
                log.warning(
                    "Revisão identidade=%s motivo=%s",
                    short_id(lanc.identidade),
                    motivo,
                )
                revisao += 1
                continue
            assert paciente is not None
            lanc.paciente = paciente
            campos = sorted(paciente.campos_preenchidos().keys())
            log.info(
                "OK identidade=%s campos=%s",
                short_id(lanc.identidade),
                ",".join(campos),
            )
            store.upsert(lanc, EstadoLancamento.PENDENTE, motivo="fetch ok")
            ok += 1
    finally:
        connector.close()

    log.info("Fetch finalizado: ok=%s revisao=%s erros=%s", ok, revisao, erros)
    return 0 if erros == 0 else 1


def cmd_run(
    cfg: AppConfig,
    *,
    planilha: Optional[Path] = None,
    limit: Optional[int] = None,
    dry_run: bool = True,
) -> int:
    if not dry_run:
        try:
            validate_config(cfg, for_live=True, for_biodata_real=(cfg.sistema_origem == "biodata"))
        except Exception as exc:
            log.error("Live bloqueado: %s", exc)
            return 2

    lancamentos = validate_all(cfg, planilha)
    if limit is not None:
        lancamentos = lancamentos[:limit]

    try:
        connector = build_connector(cfg.sistema_origem, cfg)
    except BiodataMappingError as exc:
        log.error("%s", exc)
        return 2

    store = _store(cfg)
    automator = ApacAutomator(cfg, dry_run=dry_run)
    if not dry_run:
        try:
            automator.assert_live_allowed()
        except ApacBlockedError as exc:
            log.error("%s", exc)
            connector.close()
            return 2

    processados = 0
    try:
        for lanc in lancamentos:
            pular, motivo_pulo = store.deve_pular(lanc)
            if pular:
                log.info(
                    "Pulando identidade=%s (%s)",
                    short_id(lanc.identidade),
                    motivo_pulo,
                )
                continue
            if motivo_pulo == "entrada alterada desde a última execução":
                log.warning(
                    "Entrada alterada identidade=%s — reprocessando com novo hash.",
                    short_id(lanc.identidade),
                )

            store.upsert(lanc, EstadoLancamento.EM_PROCESSAMENTO)
            paciente, motivo = resolver_paciente(connector, lanc)
            if motivo:
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo=motivo,
                )
                log.warning(
                    "Revisão identidade=%s motivo=%s — não avança para APAC.",
                    short_id(lanc.identidade),
                    motivo,
                )
                continue

            lanc.paciente = paciente
            try:
                result = automator.run_lancamento(lanc)
            except ApacInterruptedError as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.SALVAMENTO_INCERTO
                    if exc.durante_salvamento
                    else EstadoLancamento.ERRO,
                    motivo=str(exc),
                    precisa_reconciliar=exc.durante_salvamento,
                )
                log.error(
                    "Interrupção identidade=%s — fluxo interrompido (não segue para outro).",
                    short_id(lanc.identidade),
                )
                return 3
            except ApacBlockedError as exc:
                store.upsert(lanc, EstadoLancamento.ERRO, motivo=str(exc))
                log.error("Bloqueio APAC identidade=%s", short_id(lanc.identidade))
                return 2
            except Exception as exc:
                store.upsert(
                    lanc,
                    EstadoLancamento.ERRO,
                    motivo=type(exc).__name__,
                )
                log.error(
                    "Erro inesperado identidade=%s tipo=%s — parando lote.",
                    short_id(lanc.identidade),
                    type(exc).__name__,
                )
                return 1

            if not result.ok:
                store.upsert(lanc, EstadoLancamento.ERRO, motivo=result.message)
                log.error(
                    "Falha identidade=%s — não avança (tela/estado inesperado).",
                    short_id(lanc.identidade),
                )
                return 1

            if dry_run or result.parado_antes_salvar:
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo=result.message,
                )
            else:
                # Só marca concluído com confirmação explícita de sucesso (ainda não mapeada)
                store.upsert(
                    lanc,
                    EstadoLancamento.AGUARDANDO_REVISAO,
                    motivo="sequência enviada; confirme sucesso no APAC antes de concluir",
                )
            processados += 1
    finally:
        connector.close()

    log.info("Run finalizado (dry_run=%s): processados=%s", dry_run, processados)
    return 0


def cmd_status(cfg: AppConfig) -> int:
    store = _store(cfg)
    rows = store.list_by_clinica(cfg.clinica_id)
    if not rows:
        log.info("Nenhum registro de progresso para clinica_id=%s", cfg.clinica_id)
        return 0
    contagem: dict[str, int] = {}
    for r in rows:
        contagem[r.estado.value] = contagem.get(r.estado.value, 0) + 1
    log.info("Progresso clinica_id=%s total=%s", cfg.clinica_id, len(rows))
    for estado, n in sorted(contagem.items()):
        log.info("  %s: %s", estado, n)
    incerto = [r for r in rows if r.precisa_reconciliar or r.estado == EstadoLancamento.SALVAMENTO_INCERTO]
    if incerto:
        log.warning(
            "%s registro(s) exigem reconciliação manual no APAC (não reenviar automaticamente).",
            len(incerto),
        )
    return 0
