"""Pré-check de dados obrigatórios antes do gerar-set."""

from pathlib import Path

from apac_bot.models import EstadoLancamento, Lancamento, PacienteDados
from apac_bot.pipeline import validar_dados_obrigatorios_apac
from apac_bot.progress import ProgressStore, filtrar_pendentes_lote


def _paciente_ok(**overrides) -> PacienteDados:
    base = dict(
        id_paciente="BIO-1",
        cpf="529.982.247-25",
        nome="MARIA SILVA",
        nome_mae="ANA SILVA",
        nascimento="01/01/1980",
        sexo="F",
    )
    base.update(overrides)
    return PacienteDados(**base)


def _lanc(nome: str = "MARIA SILVA FICTICIA", num: str = "1-1") -> Lancamento:
    return Lancamento(
        clinica_id="c1",
        numeracao_original=num,
        numeracao_apac=num.replace("-", "/"),
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome=nome,
        id_paciente="BIO-1001",
    )


def test_validar_ok():
    assert validar_dados_obrigatorios_apac(_paciente_ok(), "MARIA SILVA") is None


def test_validar_ok_so_cns():
    p = _paciente_ok(cpf=None, cns="708107527671032")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") is None


def test_validar_ok_cpf_com_cns_tambem():
    p = _paciente_ok(cns="708107527671032")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") is None


def test_validar_paciente_none():
    motivo = validar_dados_obrigatorios_apac(None, "X")
    assert motivo is not None
    assert "cpf/cns" in motivo
    assert "nome_mae" in motivo
    assert "nascimento" in motivo
    assert "sexo" in motivo


def test_validar_falta_cpf_e_cns():
    p = _paciente_ok(cpf=None, cns=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: cpf/cns"


def test_validar_cns_incompleto_sem_cpf():
    p = _paciente_ok(cpf=None, cns="123")
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: cpf/cns"


def test_validar_falta_mae():
    p = _paciente_ok(nome_mae=None)
    assert "nome_mae" in (validar_dados_obrigatorios_apac(p, "MARIA SILVA") or "")


def test_validar_mae_igual_paciente():
    p = _paciente_ok(nome_mae="MARIA SILVA")
    assert "nome_mae" in (validar_dados_obrigatorios_apac(p, "MARIA SILVA") or "")


def test_validar_falta_nascimento():
    p = _paciente_ok(nascimento=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: nascimento"


def test_validar_falta_sexo():
    p = _paciente_ok(sexo=None)
    assert validar_dados_obrigatorios_apac(p, "MARIA SILVA") == "faltam: sexo"


def test_validar_varios_faltando():
    p = _paciente_ok(cpf="", cns="", nascimento="", sexo="")
    motivo = validar_dados_obrigatorios_apac(p, "MARIA SILVA")
    assert motivo == "faltam: cpf/cns, nascimento, sexo"


def test_aguardando_revisao_nao_e_pulado(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    lanc = _lanc()
    store.upsert(lanc, EstadoLancamento.AGUARDANDO_REVISAO, motivo="faltam: sexo")
    pular, motivo = store.deve_pular(lanc)
    assert pular is False
    assert motivo is None


def test_filtrar_pendentes_inclui_aguardando_revisao(tmp_path: Path):
    store = ProgressStore(tmp_path / "p.db")
    a = _lanc("AAA", "111-1")
    b = _lanc("BBB", "222-2")
    store.upsert(a, EstadoLancamento.AGUARDANDO_REVISAO, motivo="faltam: cpf")
    store.upsert(b, EstadoLancamento.CONCLUIDO, motivo="ok")
    pendentes, pulados, _alterados = filtrar_pendentes_lote([a, b], store)
    assert [l.paciente_nome for l in pendentes] == ["AAA"]
    assert len(pulados) == 1
    assert pulados[0][0].paciente_nome == "BBB"
