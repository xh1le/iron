import os

from backend.config import Settings, iron_home, load_settings, merge_settings, save_settings


def test_iron_home_default(monkeypatch):
    monkeypatch.delenv("IRON_HOME", raising=False)
    assert iron_home().name == ".iron"


def test_iron_home_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_HOME", str(tmp_path / "isolated"))
    assert iron_home() == (tmp_path / "isolated").resolve()
    assert iron_home().exists()


def test_settings_roundtrip_with_isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_HOME", str(tmp_path / "cfg"))
    settings = Settings(model="gemma4:e2b", temperature=0.4)
    save_settings(settings)
    loaded = load_settings()
    assert loaded.model == "gemma4:e2b"
    assert loaded.temperature == 0.4


def test_merge_settings_ignores_none(tmp_path, monkeypatch):
    monkeypatch.setenv("IRON_HOME", str(tmp_path / "cfg2"))
    current = Settings(model="a")
    merged = merge_settings(current, {"model": None, "temperature": 0.9})
    assert merged.model == "a"
    assert merged.temperature == 0.9
