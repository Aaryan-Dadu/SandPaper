from pathlib import Path

from click.testing import CliRunner

from sandpaper_py.cli import main


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "interactive" in result.output.lower()
    assert "run" in result.output.lower()


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0


def test_run_subcommand_help():
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--url" in result.output
    assert "--format" in result.output
    assert "--auto-paginate" in result.output


def test_config_show(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0


def test_preset_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sandpaper_py.presets.presets_dir", lambda: tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["preset", "list"])
    assert result.exit_code == 0
