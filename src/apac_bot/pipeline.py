from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

from apac_bot.config import AppConfig, SISTEMA_ORIGEM_EYECARE, validate_config
from apac_bot.logging_safe import setup_logging
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.normalize import (
    nascimento_ddmmaaaa,
    sexo_para_apac,
    tem_cns_valido,
    tem_cpf_valido,
)
from apac_bot.sheet import (
    load_lancamentos,
    nome_chave_prontuario,
    nome_mae_valido,
    prontuario_so_digitos,
)

log = setup_logging()


class PipelineError(Exception):
    pass


def validar_dados_obrigatorios_apac(
    paciente: Optional[PacienteDados],
    paciente_nome: str,
) -> Optional[str]:
    """
    Pré-check antes do gerar-set.
    Retorna None se (CPF ou CNS), nome da mãe, nascimento e sexo estiverem ok;
    senão string com os campos faltando (ex.: "faltam: cpf/cns, nome_mae").
    """
    if paciente is None:
        return "faltam: cpf/cns, nome_mae, nascimento, sexo"

    faltam: list[str] = []
    if not tem_cpf_valido(paciente.cpf) and not tem_cns_valido(paciente.cns):
        faltam.append("cpf/cns")
    if not nome_mae_valido(paciente.nome_mae, paciente_nome):
        faltam.append("nome_mae")
    if not nascimento_ddmmaaaa(paciente.nascimento):
        faltam.append("nascimento")
    if not sexo_para_apac(paciente.sexo):
        faltam.append("sexo")
    if not faltam:
        return None
    return "faltam: " + ", ".join(faltam)


def validate_all(cfg: AppConfig, planilha: Optional[Path] = None) -> list[Lancamento]:
    avisos = validate_config(cfg)
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


def resolver_paciente_eyecare(
    connector,
    lanc: Lancamento,
) -> tuple[Optional[PacienteDados], Optional[str]]:
    """Eyecare/IMO: cruzamento exclusivo por PRONT; sem fallback por nome."""
    pront = prontuario_so_digitos(lanc.prontuario or "") or (
        lanc.prontuario or ""
    ).strip()
    if not pront:
        return None, "PRONT ausente na planilha de faturamento"

    log.info("Buscando Eyecare por prontuario=%s", pront)
    encontrado = connector.buscar_por_prontuario(pront)
    if encontrado is None:
        return (
            None,
            f"prontuário {pront} não encontrado na planilha de pacientes",
        )

    chave_fat = nome_chave_prontuario(lanc.paciente_nome or "")
    chave_cad = nome_chave_prontuario(encontrado.nome or "")
    if chave_fat and chave_cad and chave_fat != chave_cad:
        return (
            None,
            f"prontuário {pront}: nome divergente "
            f"(faturamento: {lanc.paciente_nome} / cadastro: {encontrado.nome})",
        )

    cns_fat = str((lanc.extras or {}).get("cns_faturamento") or "").strip()
    if cns_fat and not tem_cns_valido(encontrado.cns):
        encontrado = replace(encontrado, cns=cns_fat)

    return encontrado, None


def resolver_paciente(
    connector,
    lanc: Lancamento,
    *,
    origem: str = "",
) -> tuple[Optional[PacienteDados], Optional[str]]:
    """
    Ordem:
      1) prontuario (2a planilha) — busca pelo numero no dialogo
      2) id_paciente
      3) nome (+ desambiguacao CPF / prontuario)
    Retorna (paciente|None, motivo_revisao|None).
    """
    origem_norm = str(origem or "").strip().lower()
    if origem_norm in (SISTEMA_ORIGEM_EYECARE, "icare"):
        return resolver_paciente_eyecare(connector, lanc)

    pront = "".join(ch for ch in str(lanc.prontuario or "") if ch.isdigit())
    if pront:
        log.info("Buscando origem por prontuario=%s", pront)
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


resolver_paciente_icare = resolver_paciente_eyecare
