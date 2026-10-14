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


def test_detect_comfy_root_normalizes_models_folder(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    actual_base = tmp_path / "Comfy Desktop Data"
    models = actual_base / "models"
    models.mkdir(parents=True)

    cfg = appdata / "ComfyUI" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"sharedModelsPath": str(models)}), encoding="utf-8")

    monkeypatch.setenv("APPDATA", str(appdata))

    assert config.normalize_comfy_base(models) == actual_base
    assert config.detect_comfy_root() == actual_base
    assert config.detect_comfy_root() / "models" == models


def test_detect_modern_comfy_desktop_installation_root(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    user_data = appdata / "comfyui-desktop-2"
    user_data.mkdir(parents=True)

    older_install = tmp_path / "OldInstall"
    newer_install = tmp_path / "NewInstall"
    (older_install / "ComfyUI" / "models").mkdir(parents=True)
    (newer_install / "ComfyUI" / "models").mkdir(parents=True)

    (user_data / "installations.json").write_text(
        json.dumps([
            {
                "id": "old",
                "status": "installed",
                "installPath": str(older_install),
                "lastLaunchedAt": 100,
            },
            {
                "id": "new",
                "status": "installed",
                "installPath": str(newer_install),
                "lastLaunchedAt": 200,
            },
        ]),
        encoding="utf-8",
    )

    # Stale legacy config points at the Electron app directory. Modern installation
    # records must win because that is where current Comfy Desktop launches ComfyUI.
    stale = localappdata / "Programs" / "Comfy Desktop"
    (stale / "models").mkdir(parents=True)
    legacy_cfg = appdata / "ComfyUI" / "config.json"
    legacy_cfg.parent.mkdir(parents=True)
    legacy_cfg.write_text(json.dumps({"basePath": str(stale)}), encoding="utf-8")

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))

    assert config.detect_comfy_root() == newer_install / "ComfyUI"
