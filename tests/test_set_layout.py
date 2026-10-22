"""Golden test do layout INTERNO a partir de tests/fixtures/APOFTAL9.txt."""

from __future__ import annotations

from pathlib import Path

from apac_bot.set_layout import (
    CabecalhoSet,
    CidGeralSet,
    CorpoApacSet,
    PacienteSetRecord,
    ProcedimentoSet,
    calcular_smt_vrf,
    datas_competencia,
    montar_arquivo,
    montar_cabecalho,
    montar_cid_06,
    montar_corpo_14,
    montar_proc_13,
    nome_arquivo_set,
    ultimo_dia_mes,
)

FIXTURE = Path(__file__).parent / "fixtures" / "APOFTAL9.txt"


def _slice(line: str, ini: int, fim: int) -> str:
    return line[ini - 1 : fim]


def test_nome_arquivo_set():
    assert nome_arquivo_set("202609", "padrao") == "APOFTA09.SET"
    assert nome_arquivo_set("202609", "glaucoma") == "APGLAU09.SET"
    assert nome_arquivo_set("202610", "glaucoma") == "APGLAU10.OUT"
    assert nome_arquivo_set("202612", "padrao") == "APOFTA12.DEZ"
    assert nome_arquivo_set("202601", "padrao") == "APOFTA01.JAN"


def test_calcular_smt_vrf_um_paciente():
    # (405050372 + 1 + 2126205409218) % 1111 + 1111 == 1905
    pac = PacienteSetRecord(
        corpo=CorpoApacSet(
            competencia="202609",
            numeracao="2126205409218",
            uf_ibge="21",
            cnes="6618839",
            data_proc="20260901",
            data_ini_val="20260901",
            data_fim_val="20260930",
            tipo_atendimento="00",
            tipo_apac="3",
            nome="A",
            nome_mae="B",
            logradouro="C",
            numero="1",
            complemento="",
            cep="65000000",
            municipio_ibge="211230",
            nascimento="19800101",
            sexo="M",
            medico_responsavel="D",
            codigo_procedimento="0405050372",
            motivo_saida="12",
            data_obito_alta="20260930",
            autorizador_nome="E",
            cns_paciente="",
            cns_medico="705609469670213",
            cns_autorizador="708107527671032",
            cid_causas="",
            prontuario="0000000001",
            cnes_solicitante="6618839",
            data_solicitacao="20260901",
            data_autorizacao="20260901",
            cod_orgao_emiss="M211130001",
            carater_atend="01",
            apac_anterior="0000000000000",
            raca="03",
            nome_responsavel_pac="O MESMO",
            nacionalidade="010",
            etnia="",
            codigo_logradouro="008",
            bairro="CENTRO",
            ddd="",
            telefone="",
            email="",
            cns_executante="701003891196892",
            cpf="03345250390",
            ine="",
            situacao_rua="N",
            fonte_orcamentaria="",
            emendas="",
            sem_cpf="N",
        ),
        cid=CidGeralSet(
            competencia="202609",
            numeracao="2126205409218",
            cid_principal="H250",
        ),
        procedimentos=(
            ProcedimentoSet(
                competencia="202609",
                numeracao="2126205409218",
                codigo_procedimento="0405050372",
                cbo="225265",
                quantidade="0000001",
            ),
        ),
    )
    assert calcular_smt_vrf([pac]) == "1905"


def test_golden_regen_igual_fixture():
    raw = FIXTURE.read_bytes()
    text = raw.decode("latin-1")
    assert text.endswith("\x1a")
    lines = text.replace("\x1a", "").split("\r\n")
    lines = [ln for ln in lines if ln]
    assert lines[0].startswith("01#APAC")
    assert len(lines[0]) == 134

    h = lines[0]
    smt_fixture = _slice(h, 20, 23)
    assert smt_fixture == "1294"
    cab = CabecalhoSet(
        competencia=_slice(h, 8, 13),
        qtd_apac=int(_slice(h, 14, 19)),
        smt_vrf="0000",
        orgao_origem=_slice(h, 24, 53).rstrip(),
        sigla=_slice(h, 54, 59),
        cgc=_slice(h, 60, 73),
        orgao_destino=_slice(h, 74, 113).rstrip(),
        destino_in=_slice(h, 114, 114),
        data_geracao=_slice(h, 115, 122),
        versao=_slice(h, 123, 134).rstrip(),
    )

    pacientes: list[PacienteSetRecord] = []
    i = 1
    while i < len(lines):
        b, c06 = lines[i], lines[i + 1]
        assert b.startswith("14") and len(b) == 537
        assert c06.startswith("06")
        corpo = CorpoApacSet(
            competencia=_slice(b, 3, 8),
            numeracao=_slice(b, 9, 21),
            uf_ibge=_slice(b, 22, 23),
            cnes=_slice(b, 24, 30),
            data_proc=_slice(b, 31, 38),
            data_ini_val=_slice(b, 39, 46),
            data_fim_val=_slice(b, 47, 54),
            tipo_atendimento=_slice(b, 55, 56),
            tipo_apac=_slice(b, 57, 57),
            nome=_slice(b, 58, 87).rstrip(),
            nome_mae=_slice(b, 88, 117).rstrip(),
            logradouro=_slice(b, 118, 147).rstrip(),
            numero=_slice(b, 148, 152).rstrip(),
            complemento=_slice(b, 153, 162),
            cep=_slice(b, 163, 170),
            municipio_ibge=_slice(b, 171, 177).rstrip(),
            nascimento=_slice(b, 178, 185),
            sexo=_slice(b, 186, 186),
            medico_responsavel=_slice(b, 187, 216).rstrip(),
            codigo_procedimento=_slice(b, 217, 226),
            motivo_saida=_slice(b, 227, 228),
            data_obito_alta=_slice(b, 229, 236),
            autorizador_nome=_slice(b, 237, 266).rstrip(),
            cns_paciente=_slice(b, 267, 281).strip(),
            cns_medico=_slice(b, 282, 296),
            cns_autorizador=_slice(b, 297, 311),
            cid_causas=_slice(b, 312, 315),
            prontuario=_slice(b, 316, 325),
            cnes_solicitante=_slice(b, 326, 332),
            data_solicitacao=_slice(b, 333, 340),
            data_autorizacao=_slice(b, 341, 348),
            cod_orgao_emiss=_slice(b, 349, 358),
            carater_atend=_slice(b, 359, 360),
            apac_anterior=_slice(b, 361, 373),
            raca=_slice(b, 374, 375),
            nome_responsavel_pac=_slice(b, 376, 405).rstrip(),
            nacionalidade=_slice(b, 406, 408),
            etnia=_slice(b, 409, 412),
            codigo_logradouro=_slice(b, 413, 415),
            bairro=_slice(b, 416, 445).rstrip(),
            ddd=_slice(b, 446, 447),
            telefone=_slice(b, 448, 456),
            email=_slice(b, 457, 496),
            cns_executante=_slice(b, 497, 511),
            cpf=_slice(b, 512, 522),
            ine=_slice(b, 523, 532),
            situacao_rua=_slice(b, 533, 533),
            fonte_orcamentaria=_slice(b, 534, 535),
            emendas=_slice(b, 536, 536),
            sem_cpf=_slice(b, 537, 537),
        )
        assert montar_corpo_14(corpo) == b

        cid = CidGeralSet(
            competencia=_slice(c06, 3, 8),
            numeracao=_slice(c06, 9, 21),
            cid_principal=_slice(c06, 22, 25).rstrip(),
        )
        assert montar_cid_06(cid) == c06

        i += 2
        procs: list[ProcedimentoSet] = []
        while i < len(lines) and lines[i].startswith("13"):
            p13 = lines[i]
            proc = ProcedimentoSet(
                competencia=_slice(p13, 3, 8),
                numeracao=_slice(p13, 9, 21),
                codigo_procedimento=_slice(p13, 22, 31),
                cbo=_slice(p13, 32, 37),
                quantidade=_slice(p13, 38, 44),
                cnpj_cessao=_slice(p13, 45, 58),
                nota_fiscal=_slice(p13, 59, 64),
                cid_principal=_slice(p13, 65, 68),
                cid_secundario=_slice(p13, 69, 72),
                codigo_servico=_slice(p13, 73, 75),
                codigo_classificacao=_slice(p13, 76, 78),
                equipe_seq=_slice(p13, 79, 86),
                equipe_area=_slice(p13, 87, 90),
                cnes_terceiro=_slice(p13, 91, 97),
            )
            assert montar_proc_13(proc) == p13
            procs.append(proc)
            i += 1
        assert procs, "paciente sem linha 13"
        pacientes.append(
            PacienteSetRecord(corpo=corpo, cid=cid, procedimentos=tuple(procs))
        )

    assert len(pacientes) == 3
    assert calcular_smt_vrf(pacientes) == smt_fixture
    regenerated = montar_arquivo(cab, pacientes)
    assert regenerated == raw


def test_calcular_smt_vrf_soma_todos_procedimentos():
    """SMT soma codigo+qtd+numeracao de cada linha 13."""
    base_proc = dict(
        competencia="202609",
        numeracao="2126205409218",
        cbo="225265",
        quantidade="0000001",
    )
    pac = PacienteSetRecord(
        corpo=CorpoApacSet(
            competencia="202609",
            numeracao="2126205409218",
            uf_ibge="21",
            cnes="6618839",
            data_proc="20260901",
            data_ini_val="20260901",
            data_fim_val="20260930",
            tipo_atendimento="07",
            tipo_apac="1",
            nome="A",
            nome_mae="B",
            logradouro="C",
            numero="1",
            complemento="",
            cep="65000000",
            municipio_ibge="211230",
            nascimento="19800101",
            sexo="M",
            medico_responsavel="D",
            codigo_procedimento="0303050160",
            motivo_saida="15",
            data_obito_alta="20261130",
            autorizador_nome="E",
            cns_paciente="",
            cns_medico="705609469670213",
            cns_autorizador="708107527671032",
            cid_causas="",
            prontuario="0000000001",
            cnes_solicitante="6618839",
            data_solicitacao="20260901",
            data_autorizacao="20260901",
            cod_orgao_emiss="E210000001",
            carater_atend="01",
            apac_anterior="0000000000000",
            raca="03",
            nome_responsavel_pac="O MESMO",
            nacionalidade="010",
            etnia="",
            codigo_logradouro="008",
            bairro="CENTRO",
            ddd="",
            telefone="",
            email="",
            cns_executante="701003891196892",
            cpf="03345250390",
            ine="",
            situacao_rua="N",
            fonte_orcamentaria="",
            emendas="",
            sem_cpf="N",
        ),
        cid=CidGeralSet(
            competencia="202609",
            numeracao="2126205409218",
            cid_principal="H401",
        ),
        procedimentos=(
            ProcedimentoSet(**base_proc, codigo_procedimento="0303050160"),
            ProcedimentoSet(**base_proc, codigo_procedimento="0303050187"),
            ProcedimentoSet(**base_proc, codigo_procedimento="0303050195"),
        ),
    )
    # 3 * (proc + 1 + numeracao) — soma dos tres codigos
    esperado_total = (
        303050160
        + 303050187
        + 303050195
        + 3 * 1
        + 3 * 2126205409218
    )
    assert calcular_smt_vrf([pac]) == str(
        (esperado_total % 1111) + 1111
    ).zfill(4)

    cab = CabecalhoSet(
        competencia="202609",
        qtd_apac=1,
        smt_vrf="0000",
        orgao_origem="CLINICA",
        sigla="CSMG",
        cgc="01192155000210",
        orgao_destino="SECRETARIA",
        destino_in="E",
        data_geracao="20261001",
        versao="Versao 04.01",
    )
    raw = montar_arquivo(cab, [pac])
    text = raw.decode("latin-1").replace("\x1a", "")
    lines = [ln for ln in text.split("\r\n") if ln]
    assert lines[1].startswith("14")
    assert lines[2].startswith("06")
    assert sum(1 for ln in lines if ln.startswith("13")) == 3
    assert _slice(lines[3], 22, 31) == "0303050160"
    assert _slice(lines[4], 22, 31) == "0303050187"
    assert _slice(lines[5], 22, 31) == "0303050195"


def test_datas_competencia_padrao():
    ini, fim = datas_competencia("202609")
    assert ini == "20260901"
    assert fim == "20260930"


def test_datas_competencia_glaucoma_fim_mais_dois_meses():
    ini, fim = datas_competencia("202609", fim_offset_meses=2)
    assert ini == "20260901"
    assert fim == "20261130"


def test_datas_competencia_glaucoma_virada_de_ano():
    ini, fim = datas_competencia("202611", fim_offset_meses=2)
    assert ini == "20261101"
    assert fim == "20270131"


def test_ultimo_dia_mes_fevereiro_bissexto():
    assert ultimo_dia_mes(2024, 2, 0).strftime("%Y%m%d") == "20240229"
    assert ultimo_dia_mes(2023, 12, 2).strftime("%Y%m%d") == "20240229"
