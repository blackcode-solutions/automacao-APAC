from apac_bot.config import biodata_modo
from apac_bot.connectors.base import OrigemConnector
from apac_bot.connectors.biodata import BiodataConnector, BiodataMappingError
from apac_bot.connectors.biodata_api import BiodataApiConnector, BiodataApiError
from apac_bot.connectors.mock_biodata import MockBiodataConnector

__all__ = [
    "OrigemConnector",
    "BiodataConnector",
    "BiodataApiConnector",
    "BiodataApiError",
    "BiodataMappingError",
    "MockBiodataConnector",
    "build_connector",
]


def build_connector(sistema_origem: str, cfg) -> OrigemConnector:
    origem = sistema_origem.lower()
    if origem == "mock":
        return MockBiodataConnector()
    if origem == "biodata":
        if biodata_modo(cfg) == "api":
            return BiodataApiConnector(cfg)
        return BiodataConnector(cfg)
    raise ValueError(f"sistema_origem desconhecido: {sistema_origem}")
