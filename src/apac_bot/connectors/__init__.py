from apac_bot.connectors.base import OrigemConnector
from apac_bot.connectors.biodata import BiodataConnector, BiodataMappingError
from apac_bot.connectors.mock_biodata import MockBiodataConnector

__all__ = [
    "OrigemConnector",
    "BiodataConnector",
    "BiodataMappingError",
    "MockBiodataConnector",
]


def build_connector(sistema_origem: str, cfg) -> OrigemConnector:
    origem = sistema_origem.lower()
    if origem == "mock":
        return MockBiodataConnector()
    if origem == "biodata":
        return BiodataConnector(cfg)
    raise ValueError(f"sistema_origem desconhecido: {sistema_origem}")
