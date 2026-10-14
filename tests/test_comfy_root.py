from pathlib import Path
import json

from zeroreels import config


def test_detect_comfy_root_prefers_desktop_base_path(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    actual = tmp_path / "ComfyData"
    (actual / "models").mkdir(parents=True)

    wrong_install = localappdata / "Programs" / "Comfy Desktop"
    (wrong_install / "models").mkdir(parents=True)

    cfg = appdata / "ComfyUI" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"basePath": str(actual)}), encoding="utf-8")

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))

    assert config.detect_comfy_root() == actual
    assert config.is_comfy_program_install_root(wrong_install)
