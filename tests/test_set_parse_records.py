"""Round-trip records_from_set_file."""

from pathlib import Path

from apac_bot.set_parse import records_from_set_file

FIXTURE = Path(__file__).parent / "fixtures" / "APOFTAL9.txt"


def test_records_from_set_file_fixture():
    comp, records = records_from_set_file(FIXTURE)
    assert comp == "202609"
    assert len(records) == 3
    assert all(r.procedimentos for r in records)
