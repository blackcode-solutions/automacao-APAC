from apac_bot.config import biodata_modo, sistema_origem_canonical
from apac_bot.connectors.base import OrigemConnector
from apac_bot.connectors.biodata import BiodataConnector, BiodataMappingError
from apac_bot.connectors.biodata_api import BiodataApiConnector, BiodataApiError
from apac_bot.connectors.icare_sheet import EyecareConnector, IcareSheetConnector
from apac_bot.connectors.mock_biodata import MockBiodataConnector
from apac_bot.icare_pacientes import IcareSheetError

__all__ = [
    "OrigemConnector",
    "BiodataConnector",
    "BiodataApiConnector",
    "BiodataApiError",
    "BiodataMappingError",
    "EyecareConnector",
    "IcareSheetConnector",
    "IcareSheetError",
    "MockBiodataConnector",
    "build_connector",
]


def build_connector(sistema_origem: str, cfg) -> OrigemConnector:
    origem = sistema_origem_canonical(sistema_origem)
    if origem == "mock":
        return MockBiodataConnector()
    if origem == "biodata":
        if biodata_modo(cfg) == "api":
            return BiodataApiConnector(cfg)
        return BiodataConnector(cfg)
    if origem == "eyecare":
        return EyecareConnector(cfg)
    raise ValueError(f"sistema_origem desconhecido: {sistema_origem}")
