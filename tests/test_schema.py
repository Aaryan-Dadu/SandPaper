from sandpaper_py.schema import infer_column_type, summarize
from sandpaper_py.types import ExtractedTable


def test_infer_integer():
    assert infer_column_type(["1", "2", "3", "4"]) == "integer"


def test_infer_currency():
    assert infer_column_type(["$1.00", "$2.00", "$10.00", "$3.50"]) == "currency"


def test_infer_date():
    assert infer_column_type(["2024-01-01", "2024-02-15", "2024-03-30"]) == "date"


def test_infer_boolean():
    assert infer_column_type(["true", "false", "yes", "no"]) == "boolean"


def test_infer_string_when_mixed():
    assert infer_column_type(["1", "abc", "$3", "2024-01-01"]) == "string"


def test_summarize_counts():
    table = ExtractedTable(
        columns={
            "n": ["1", "2", "3"],
            "name": ["a", "", "c"],
        }
    )
    stats = summarize(table)
    assert stats.rows == 3
    by_name = {c.name: c for c in stats.columns}
    assert by_name["n"].inferred_type == "integer"
    assert by_name["name"].non_empty == 2
    assert by_name["name"].empty == 1
    assert by_name["name"].unique == 3
