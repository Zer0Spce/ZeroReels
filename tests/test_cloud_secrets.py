from __future__ import annotations

import os
import uuid

import pytest

from zeroreels import cloud_secrets


def test_windows_credential_manager_round_trip():
    if os.name != "nt":
        pytest.skip("Windows Credential Manager test")
    target = "ZeroReels/Test-" + uuid.uuid4().hex
    value = "zr-test-secret-" + uuid.uuid4().hex
    try:
        cloud_secrets._windows_write(target, value)
        assert cloud_secrets._windows_read(target) == value
    finally:
        cloud_secrets._windows_delete(target)
    assert cloud_secrets._windows_read(target) == ""
