from apac_bot.connectors.mock_biodata import MockBiodataConnector
from apac_bot.models import Lancamento, PacienteDados
from apac_bot.pipeline import resolver_paciente


def _lanc(nome: str) -> Lancamento:
    return Lancamento(
        clinica_id="c1",
        numeracao_original="1-1",
        numeracao_apac="1/1",
        codigo_original="01",
        codigo_apac="01",
        auditor="A",
        paciente_nome=nome,
    )


def test_busca_por_id():
    c = MockBiodataConnector()
    p = c.buscar_por_id("BIO-1001")
    assert p is not None
    assert p.nome == "MARIA SILVA FICTICIA"


def test_busca_nome_ambigua():
    c = MockBiodataConnector()
    res = c.buscar_por_nome("PACIENTE AMBIGUO")
    assert len(res) == 2


def test_resolver_ambiguidade_ambos_com_cpf_para_revisao():
    """Dois com CPF → continua ambígua."""
    c = MockBiodataConnector()
    paciente, motivo = resolver_paciente(c, _lanc("PACIENTE AMBIGUO"))
    assert paciente is None
    assert motivo is not None
    assert "ambígua" in motivo
    assert "com CPF" in motivo


def test_resolver_ambiguidade_so_um_com_cpf():
    """Vários nomes iguais, só um com CPF → escolhe esse."""
    pacientes = [
        PacienteDados(
            id_paciente="BIO-X1",
            cpf=None,
            nome="PACIENTE MISTO",
            nome_mae="MAE SEM CPF",
        ),
        PacienteDados(
            id_paciente="BIO-X2",
            cpf="529.982.247-25",
            nome="PACIENTE MISTO",
            nome_mae="MAE COM CPF",
        ),
        PacienteDados(
            id_paciente="BIO-X3",
            cpf="",
            nome="PACIENTE MISTO",
            nome_mae="MAE VAZIO",
        ),
    ]
    c = MockBiodataConnector(pacientes=pacientes)
    paciente, motivo = resolver_paciente(c, _lanc("PACIENTE MISTO"))
    assert motivo is None
    assert paciente is not None
    assert paciente.id_paciente == "BIO-X2"
    assert paciente.cpf == "529.982.247-25"


def test_resolver_ambiguidade_nenhum_com_cpf():
    pacientes = [
        PacienteDados(id_paciente="A", cpf=None, nome="SEM CPF DUPLO"),
        PacienteDados(id_paciente="B", cpf="", nome="SEM CPF DUPLO"),
    ]
    c = MockBiodataConnector(pacientes=pacientes)
    paciente, motivo = resolver_paciente(c, _lanc("SEM CPF DUPLO"))
    assert paciente is None
    assert motivo is not None
    assert "nenhum com CPF" in motivo


def test_resolver_ambiguidade_por_prontuario():
    """Dois com CPF + prontuario → escolhe o id correspondente."""
    c = MockBiodataConnector()
    lanc = _lanc("PACIENTE AMBIGUO")
    lanc.prontuario = "2001"  # digitos de BIO-2001
    paciente, motivo = resolver_paciente(c, lanc)
    assert motivo is None
    assert paciente is not None
    assert paciente.id_paciente == "BIO-2001"


def test_buscar_nome_filtra_prontuario():
    c = MockBiodataConnector()
    res = c.buscar_por_nome("PACIENTE AMBIGUO", prontuario="2002")
    assert len(res) == 1
    assert res[0].id_paciente == "BIO-2002"


def test_resolver_prioriza_busca_por_prontuario():
    """Com prontuario, resolve direto (sem ambiguidade por nome)."""
    c = MockBiodataConnector()
    lanc = _lanc("PACIENTE AMBIGUO")
    lanc.prontuario = "2001"
    paciente, motivo = resolver_paciente(c, lanc)
    assert motivo is None
    assert paciente is not None
    assert paciente.id_paciente == "BIO-2001"


def test_buscar_por_prontuario_direto():
    c = MockBiodataConnector()
    p = c.buscar_por_prontuario("2002")
    assert p is not None
    assert p.id_paciente == "BIO-2002"
    assert c.buscar_por_prontuario("999999") is None


def test_resolver_prontuario_inexistente_fallback_nome_ambiguo():
    c = MockBiodataConnector()
    lanc = _lanc("PACIENTE AMBIGUO")
    lanc.prontuario = "999999"
    paciente, motivo = resolver_paciente(c, lanc)
    assert paciente is None
    assert motivo is not None
    assert "ambígua" in motivo
