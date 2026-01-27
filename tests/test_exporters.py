import csv
import json
import sqlite3
from pathlib import Path

import pytest

from sandpaper_py.exceptions import ExportError
from sandpaper_py.exporters import (
    CSVExporter,
    JSONExporter,
    JSONLExporter,
    SQLiteExporter,
)
from sandpaper_py.types import ExtractedTable


@pytest.fixture
def table() -> ExtractedTable:
    return ExtractedTable(
        columns={
            "title": ["A", "B", "C"],
            "price": ["1", "2", "3"],
        }
    )


def test_csv_export(tmp_path: Path, table: ExtractedTable):
    out = tmp_path / "out.csv"
    CSVExporter().export(table, out)
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["title", "price"]
    assert rows[1] == ["A", "1"]
    assert len(rows) == 4


def test_csv_pads_unequal(tmp_path: Path):
    table = ExtractedTable(columns={"a": ["1", "2", "3"], "b": ["x"]})
    out = tmp_path / "out.csv"
    CSVExporter().export(table, out)
    rows = list(csv.reader(out.open()))
    assert rows[2] == ["2", ""]
    assert rows[3] == ["3", ""]


def test_csv_rejects_empty(tmp_path: Path):
    with pytest.raises(ExportError):
        CSVExporter().export(ExtractedTable(columns={}), tmp_path / "x.csv")


def test_json_export(tmp_path: Path, table: ExtractedTable):
    out = tmp_path / "out.json"
    JSONExporter().export(table, out)
    payload = json.loads(out.read_text())
    assert payload[0] == {"title": "A", "price": "1"}
    assert len(payload) == 3


def test_jsonl_export(tmp_path: Path, table: ExtractedTable):
    out = tmp_path / "out.jsonl"
    JSONLExporter().export(table, out)
    lines = out.read_text().strip().splitlines()
    assert json.loads(lines[0]) == {"title": "A", "price": "1"}
    assert len(lines) == 3


def test_sqlite_export(tmp_path: Path, table: ExtractedTable):
    out = tmp_path / "data.db"
    SQLiteExporter(table_name="test").export(table, out)
    with sqlite3.connect(out) as conn:
        rows = conn.execute("SELECT title, price FROM test ORDER BY title").fetchall()
    assert rows == [("A", "1"), ("B", "2"), ("C", "3")]


def test_csv_default_extension(tmp_path: Path, table: ExtractedTable):
    out = tmp_path / "data"
    written = CSVExporter().export(table, out)
    assert written.endswith(".csv")
    assert Path(written).exists()
