"""
Tests for ``GPGAuditorLogStorage``.

Regression tests for the bug where a failed GPG ``encrypt()`` (python-gnupg
returns ``False``/empty on failure) was written to the audit file as the
literal string ``"False"``, silently destroying the record with no exception.

A failed encryption must be **fatal** and must not leave an orphan record on
disk.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from typing import List
from unittest import mock

import pytest

from llm_router_api.core.auditor.log_storage.gpg import (
    DEFAULT_AUDITOR_OUT_DIR,
    GPGAuditorLogStorage,
)


def _make_storage(encrypt_result) -> GPGAuditorLogStorage:
    """
    Build a ``GPGAuditorLogStorage`` without running ``__init__`` (which
    requires a real, importable public key file on disk — a deployment
    detail we do not want to depend on in a unit test).

    ``encrypt_result`` is what the mocked ``_gpg.encrypt`` returns.
    """
    storage = GPGAuditorLogStorage.__new__(GPGAuditorLogStorage)
    fake_gpg = mock.Mock()
    fake_gpg.encrypt.return_value = encrypt_result
    storage._gpg = fake_gpg

    import_result = mock.Mock()
    import_result.fingerprints = ["FINGRPRINT00000000000000000000000000"]
    storage._import_result = import_result
    return storage


def _audit_files() -> List[str]:
    return (
        sorted(os.listdir(DEFAULT_AUDITOR_OUT_DIR))
        if DEFAULT_AUDITOR_OUT_DIR.exists()
        else []
    )


class TestEncryptFailureIsFatal:
    """A failed encryption must raise and must not persist a record."""

    def test_false_result_raises(self):
        storage = _make_storage(encrypt_result=False)
        with pytest.raises(RuntimeError):
            storage.store_log({"user": "alice"}, "request")

    def test_empty_result_raises(self):
        # gnupg may also return an empty GPGData/bytes on failure.
        storage = _make_storage(encrypt_result=b"")
        with pytest.raises(RuntimeError):
            storage.store_log({"user": "alice"}, "request")

    def test_no_record_file_created_on_failure(self):
        before = _audit_files()
        storage = _make_storage(encrypt_result=False)
        with pytest.raises(RuntimeError):
            storage.store_log({"user": "alice"}, "request")
        after = _audit_files()
        # No new .audit file should appear as a side effect of the failure.
        new_files = [f for f in after if f not in before]
        assert new_files == [], f"failure left orphan record(s): {new_files}"


class TestEncryptSuccessWritesRecord:
    """On success the (armored) encrypted payload is written to a file."""

    def test_writes_encrypted_payload(self, tmp_path, monkeypatch):
        # Point the output dir at a temp location so the test is hermetic.
        import llm_router_api.core.auditor.log_storage.gpg as gpg_mod

        monkeypatch.setattr(gpg_mod, "DEFAULT_AUDITOR_OUT_DIR", tmp_path)
        armored = "-----BEGIN PGP MESSAGE-----\nabc\n-----END PGP MESSAGE-----"

        storage = GPGAuditorLogStorage.__new__(GPGAuditorLogStorage)
        storage._gpg = mock.Mock()
        storage._gpg.encrypt.return_value = armored
        storage._import_result = mock.Mock()
        storage._import_result.fingerprints = ["F"]

        storage.store_log({"user": "alice"}, "request")

        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name.endswith(".audit")
        assert files[0].read_text(encoding="utf-8") == armored

    def test_encrypt_called_with_always_trust(self):
        storage = _make_storage(encrypt_result="ARMORED")
        storage.store_log({"a": 1}, "request")
        _, kwargs = storage._gpg.encrypt.call_args
        assert kwargs["always_trust"] is True
        assert kwargs["armor"] is True
