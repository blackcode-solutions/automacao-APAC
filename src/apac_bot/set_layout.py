"""
Layout INTERNO de exportacao APAC (tipos 01 / 14 / 06 / 13).

Gera bytes latin-1 com CRLF e SUB (0x1A) no fim, como o Magnético exporta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Sequence

from apac_bot.config import MODALIDADE_GLAUCOMA, normalizar_modalidade_cfg
from apac_bot.normalize import ymd_valido

LINE_ENDING = b"\r\n"
EOF_SUB = b"\x1a"

LEN_HEADER = 134
LEN_CORPO = 537
LEN_CID = 25
LEN_PROC = 97
SMT_VRF_MODULO = 1111


class SetLayoutError(Exception):
    """Campo ou montagem invalida para o layout INTERNO."""


def pad_char(valor: object, tam: int) -> str:
    s = "" if valor is None else str(valor)
    if len(s) > tam:
        s = s[:tam]
    return s.ljust(tam)


def pad_num(valor: object, tam: int) -> str:
    digits = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(digits) > tam:
        digits = digits[-tam:]
    return digits.zfill(tam)


def _ascii_upper(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", (texto or "").strip())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.upper()


def numeracao_13(numeracao: str) -> str:
    """13 digitos: sequencia + DV (remove hifen/barra)."""
    digits = "".join(ch for ch in str(numeracao or "") if ch.isdigit())
    if len(digits) != 13:
        raise SetLayoutError(
            f"numeracao APAC deve ter 13 digitos (obtido {len(digits)}): {numeracao!r}"
        )
    return digits


def competencia_aaaamm(valor: Optional[str]) -> str:
    s = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if len(s) == 6:
        return s
    if len(s) == 8:
        return s[:6]
    raise SetLayoutError(f"competencia invalida (esperado AAAAMM): {valor!r}")


def ultimo_dia_mes(ano: int, mes: int, offset_meses: int = 0) -> date:
    """Último dia do mês (ano, mes) + offset_meses (trata virada de ano)."""
    import calendar

    m0 = mes - 1 + offset_meses
    y = ano + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def datas_competencia(comp: str, fim_offset_meses: int = 0) -> tuple[str, str]:
    """
    Retorna (primeiro_dia, ultimo_dia) AAAAMMDD da competencia.
    fim_offset_meses: 0 = último dia do mês da competência;
    2 = último dia de competência+2 (APAC Glaucoma).
    """
    c = competencia_aaaamm(comp)
    ano, mes = int(c[:4]), int(c[4:6])
    primeiro = date(ano, mes, 1)
    ultimo = ultimo_dia_mes(ano, mes, fim_offset_meses)
    return primeiro.strftime("%Y%m%d"), ultimo.strftime("%Y%m%d")


def nascimento_aaaammdd(valor: Optional[str]) -> str:
    """Converte nascimento (DDMMAAAA / ISO / etc.) para AAAAMMDD."""
    if not valor:
        raise SetLayoutError("nascimento ausente")
    s = str(valor).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        # Preferir DDMMAAAA (origem BR); senão já AAAAMMDD.
        d, m, y = int(digits[0:2]), int(digits[2:4]), int(digits[4:8])
        if ymd_valido(y, m, d):
            return f"{digits[4:8]}{digits[2:4]}{digits[0:2]}"
        y2, m2, d2 = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        if ymd_valido(y2, m2, d2):
            return digits
        raise SetLayoutError(f"nascimento invalido: {valor!r}")
    for sep in ("/", "-", "."):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) == 3:
                a, b, c = parts
                if len(a) == 4:
                    y, m, d = a, b.zfill(2), c.zfill(2)
                else:
                    d, m, y = a.zfill(2), b.zfill(2), c
                    if len(y) == 2:
                        y = ("20" if int(y) < 50 else "19") + y
                if not ymd_valido(int(y), int(m), int(d)):
                    raise SetLayoutError(f"nascimento invalido: {valor!r}")
                return f"{y}{m}{d}"
    raise SetLayoutError(f"nascimento invalido: {valor!r}")


@dataclass(frozen=True)
class CabecalhoSet:
    competencia: str
    qtd_apac: int
    smt_vrf: str
    orgao_origem: str
    sigla: str
    cgc: str
    orgao_destino: str
    destino_in: str
    data_geracao: str
    versao: str


@dataclass(frozen=True)
class CorpoApacSet:
    competencia: str
    numeracao: str
    uf_ibge: str
    cnes: str
    data_proc: str
    data_ini_val: str
    data_fim_val: str
    tipo_atendimento: str
    tipo_apac: str
    nome: str
    nome_mae: str
    logradouro: str
    numero: str
    complemento: str
    cep: str
    municipio_ibge: str
    nascimento: str
    sexo: str
    medico_responsavel: str
    codigo_procedimento: str
    motivo_saida: str
    data_obito_alta: str
    autorizador_nome: str
    cns_paciente: str
    cns_medico: str
    cns_autorizador: str
    cid_causas: str
    prontuario: str
    cnes_solicitante: str
    data_solicitacao: str
    data_autorizacao: str
    cod_orgao_emiss: str
    carater_atend: str
    apac_anterior: str
    raca: str
    nome_responsavel_pac: str
    nacionalidade: str
    etnia: str
    codigo_logradouro: str
    bairro: str
    ddd: str
    telefone: str
    email: str
    cns_executante: str
    cpf: str
    ine: str
    situacao_rua: str
    fonte_orcamentaria: str
    emendas: str
    sem_cpf: str


@dataclass(frozen=True)
class CidGeralSet:
    competencia: str
    numeracao: str
    cid_principal: str


@dataclass(frozen=True)
class ProcedimentoSet:
    competencia: str
    numeracao: str
    codigo_procedimento: str
    cbo: str
    quantidade: str
    cnpj_cessao: str = ""
    nota_fiscal: str = ""
    cid_principal: str = ""
    cid_secundario: str = ""
    codigo_servico: str = ""
    codigo_classificacao: str = ""
    equipe_seq: str = ""
    equipe_area: str = ""
    cnes_terceiro: str = ""


@dataclass(frozen=True)
class PacienteSetRecord:
    corpo: CorpoApacSet
    cid: CidGeralSet
    procedimentos: tuple[ProcedimentoSet, ...]

    def __post_init__(self) -> None:
        if not self.procedimentos:
            raise SetLayoutError("PacienteSetRecord exige ao menos 1 procedimento")


def _digitos_como_int(valor: object) -> int:
    digits = "".join(ch for ch in str(valor or "") if ch.isdigit())
    return int(digits) if digits else 0


def calcular_smt_vrf(pacientes: Sequence[PacienteSetRecord]) -> str:
    """Campo de controle do cabecalho: (soma proc+qtd+APAC) % 1111 + 1111."""
    total = 0
    for pac in pacientes:
        for proc in pac.procedimentos:
            total += (
                _digitos_como_int(proc.codigo_procedimento)
                + _digitos_como_int(proc.quantidade)
                + _digitos_como_int(proc.numeracao)
            )
    valor = (total % SMT_VRF_MODULO) + SMT_VRF_MODULO
    return pad_num(valor, 4)


def montar_cabecalho(h: CabecalhoSet) -> str:
    parts = [
        "01",
        "#APAC",
        competencia_aaaamm(h.competencia),
        pad_num(h.qtd_apac, 6),
        pad_num(h.smt_vrf, 4),
        pad_char(_ascii_upper(h.orgao_origem), 30),
        pad_char(_ascii_upper(h.sigla), 6),
        pad_num(h.cgc, 14),
        pad_char(_ascii_upper(h.orgao_destino), 40),
        pad_char(h.destino_in, 1),
        pad_num(h.data_geracao, 8),
        # PDF cita 15; export Magnético observado usa 12 ("Versao 04.01").
        pad_char(h.versao, 12),
    ]
    line = "".join(parts)
    if len(line) != LEN_HEADER:
        raise SetLayoutError(f"cabecalho len={len(line)} esperado {LEN_HEADER}")
    return line


def _campo_num_ou_branco(valor: object, tam: int) -> str:
    """Numerico com zeros a esquerda; se vazio, espacos (como CNS paciente no exemplo)."""
    digits = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if not digits:
        return pad_char("", tam)
    return pad_num(digits, tam)


def montar_corpo_14(c: CorpoApacSet) -> str:
    mun = str(c.municipio_ibge or "")
    if mun.isdigit() and len(mun) == 6:
        mun_field = mun + " "
    else:
        mun_field = pad_char(mun, 7)

    parts = [
        "14",
        competencia_aaaamm(c.competencia),
        numeracao_13(c.numeracao),
        pad_num(c.uf_ibge, 2),
        pad_num(c.cnes, 7),
        pad_num(c.data_proc, 8),
        pad_num(c.data_ini_val, 8),
        pad_num(c.data_fim_val, 8),
        pad_num(c.tipo_atendimento, 2),
        pad_char(c.tipo_apac, 1),
        pad_char(_ascii_upper(c.nome), 30),
        pad_char(_ascii_upper(c.nome_mae), 30),
        pad_char(_ascii_upper(c.logradouro), 30),
        pad_char(c.numero, 5),
        pad_char(c.complemento, 10),
        pad_num(c.cep, 8),
        mun_field,
        pad_num(c.nascimento, 8),
        pad_char(c.sexo, 1),
        pad_char(_ascii_upper(c.medico_responsavel), 30),
        pad_num(c.codigo_procedimento, 10),
        pad_num(c.motivo_saida, 2),
        pad_num(c.data_obito_alta, 8),
        pad_char(_ascii_upper(c.autorizador_nome), 30),
        _campo_num_ou_branco(c.cns_paciente, 15),
        _campo_num_ou_branco(c.cns_medico, 15),
        _campo_num_ou_branco(c.cns_autorizador, 15),
        pad_char(c.cid_causas, 4),
        pad_char(c.prontuario, 10),
        pad_num(c.cnes_solicitante, 7),
        pad_num(c.data_solicitacao, 8),
        pad_num(c.data_autorizacao, 8),
        pad_char(c.cod_orgao_emiss, 10),
        pad_num(c.carater_atend, 2),
        pad_num(c.apac_anterior or "0", 13),
        pad_num(c.raca, 2),
        pad_char(_ascii_upper(c.nome_responsavel_pac), 30),
        pad_num(c.nacionalidade, 3),
        pad_char(c.etnia, 4),
        _campo_num_ou_branco(c.codigo_logradouro, 3),
        pad_char(_ascii_upper(c.bairro), 30),
        pad_char(c.ddd, 2),
        pad_char(c.telefone, 9),
        pad_char(c.email, 40),
        _campo_num_ou_branco(c.cns_executante, 15),
        _campo_num_ou_branco(c.cpf, 11),
        pad_char(c.ine, 10),
        pad_char(c.situacao_rua if c.situacao_rua else " ", 1),
        pad_char(c.fonte_orcamentaria, 2),
        pad_char(c.emendas if c.emendas else " ", 1),
        pad_char(c.sem_cpf if c.sem_cpf else " ", 1),
    ]
    line = "".join(parts)
    if len(line) != LEN_CORPO:
        raise SetLayoutError(f"corpo 14 len={len(line)} esperado {LEN_CORPO}")
    return line


def montar_cid_06(c: CidGeralSet) -> str:
    cid = _ascii_upper(str(c.cid_principal or "").strip())
    if len(cid) < 3:
        raise SetLayoutError(f"cid_principal invalido: {c.cid_principal!r}")
    line = (
        "06"
        + competencia_aaaamm(c.competencia)
        + numeracao_13(c.numeracao)
        + pad_char(cid, 4)
    )
    if len(line) != LEN_CID:
        raise SetLayoutError(f"cid 06 len={len(line)} esperado {LEN_CID}")
    return line


def montar_proc_13(p: ProcedimentoSet) -> str:
    parts = [
        "13",
        competencia_aaaamm(p.competencia),
        numeracao_13(p.numeracao),
        pad_num(p.codigo_procedimento, 10),
        pad_num(p.cbo, 6),
        pad_num(p.quantidade, 7),
        pad_char(p.cnpj_cessao, 14),
        pad_char(p.nota_fiscal, 6),
        pad_char(p.cid_principal, 4),
        pad_char(p.cid_secundario, 4),
        pad_num(p.codigo_servico, 3)
        if str(p.codigo_servico or "").strip()
        else pad_char("", 3),
        pad_num(p.codigo_classificacao, 3)
        if str(p.codigo_classificacao or "").strip()
        else pad_char("", 3),
        pad_char(p.equipe_seq, 8),
        pad_char(p.equipe_area, 4),
        pad_char(p.cnes_terceiro, 7),
    ]
    line = "".join(parts)
    if len(line) != LEN_PROC:
        raise SetLayoutError(f"proc 13 len={len(line)} esperado {LEN_PROC}")
    return line


def montar_arquivo(
    cabecalho: CabecalhoSet,
    pacientes: Sequence[PacienteSetRecord],
) -> bytes:
    smt_vrf = calcular_smt_vrf(pacientes)
    if cabecalho.qtd_apac != len(pacientes) or cabecalho.smt_vrf != smt_vrf:
        cabecalho = CabecalhoSet(
            competencia=cabecalho.competencia,
            qtd_apac=len(pacientes),
            smt_vrf=smt_vrf,
            orgao_origem=cabecalho.orgao_origem,
            sigla=cabecalho.sigla,
            cgc=cabecalho.cgc,
            orgao_destino=cabecalho.orgao_destino,
            destino_in=cabecalho.destino_in,
            data_geracao=cabecalho.data_geracao,
            versao=cabecalho.versao,
        )
    lines: list[str] = [montar_cabecalho(cabecalho)]
    for pac in pacientes:
        lines.append(montar_corpo_14(pac.corpo))
        lines.append(montar_cid_06(pac.cid))
        for proc in pac.procedimentos:
            lines.append(montar_proc_13(proc))
    body = LINE_ENDING.join(line.encode("latin-1") for line in lines)
    return body + LINE_ENDING + EOF_SUB


def nome_arquivo_set(competencia: str, modalidade: str) -> str:
    """APOFTA09.SET / APGLAU09.SET a partir da competencia do lote (AAAAMM).

    Basename sempre 8 caracteres: prefixo da modalidade (6) + MM (2).
    A competencia do lote ja e o mes anterior no dominio — nao subtrair 1.
    """
    c = competencia_aaaamm(competencia)
    mes = c[4:6]
    prefixo = (
        "APGLAU"
        if normalizar_modalidade_cfg(modalidade) == MODALIDADE_GLAUCOMA
        else "APOFTA"
    )
    return f"{prefixo}{mes}.SET"


def data_geracao_hoje() -> str:
    return datetime.now().strftime("%Y%m%d")
