from __future__ import annotations

import json
import os
from pathlib import Path

from .config import APP_DIR


_FALLBACK_FILE = APP_DIR / "cloud_secrets.json"
_PREFIX = "ZeroReels/"


def _windows_read(target: str) -> str:
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    pcred = ctypes.POINTER(CREDENTIALW)()
    advapi32 = ctypes.WinDLL("Advapi32.dll")
    if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        return ""
    try:
        cred = pcred.contents
        if not cred.CredentialBlob or not cred.CredentialBlobSize:
            return ""
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
    finally:
        advapi32.CredFree(pcred)


def _windows_write(target: str, value: str) -> None:
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    blob = value.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob)
    cred = CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "ZeroReels"
    cred.Comment = "ZeroReels cloud API credential"
    advapi32 = ctypes.WinDLL("Advapi32.dll")
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "Windows Credential Manager rejected the credential")


def _windows_delete(target: str) -> None:
    import ctypes

    CRED_TYPE_GENERIC = 1
    advapi32 = ctypes.WinDLL("Advapi32.dll")
    advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)


def _fallback_load() -> dict[str, str]:
    try:
        return json.loads(_FALLBACK_FILE.read_text(encoding="utf-8")) if _FALLBACK_FILE.exists() else {}
    except Exception:
        return {}


def get_secret(name: str) -> str:
    env = os.environ.get(name, "").strip()
    if env:
        return env
    target = _PREFIX + name
    if os.name == "nt":
        try:
            return _windows_read(target).strip()
        except Exception:
            return ""
    return str(_fallback_load().get(name, "")).strip()


def set_secret(name: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        delete_secret(name)
        return
    target = _PREFIX + name
    if os.name == "nt":
        _windows_write(target, value)
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data = _fallback_load()
    data[name] = value
    _FALLBACK_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        _FALLBACK_FILE.chmod(0o600)
    except OSError:
        pass


def delete_secret(name: str) -> None:
    target = _PREFIX + name
    if os.name == "nt":
        try:
            _windows_delete(target)
        except Exception:
            pass
        return
    data = _fallback_load()
    if name in data:
        del data[name]
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _FALLBACK_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
