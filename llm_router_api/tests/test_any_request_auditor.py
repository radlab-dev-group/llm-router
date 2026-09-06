"""
Unit tests for ``llm_router_api.core.auditor.auditor.AnyRequestAuditor``
and the abstract ``AuditorLogStorageInterface``.

Storage is stubbed by monkeypatching ``DEFAULT_AUDITOR_STORAGE_CLASS``;
no GPG/Kafka/network access is performed.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import logging  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.auditor import auditor as auditor_module  # noqa: E402
from llm_router_api.core.auditor.auditor import AnyRequestAuditor  # noqa: E402
from llm_router_api.core.auditor.log_storage.log_storage_interface import (  # noqa: E402
    AuditorLogStorageInterface,
)


class TestAnyRequestAuditor:
    def test_add_log_delegates_to_storage(self, monkeypatch):
        storage = mock.Mock()
        monkeypatch.setattr(
            auditor_module, "DEFAULT_AUDITOR_STORAGE_CLASS", lambda: storage
        )
        auditor = AnyRequestAuditor(logging.getLogger("test"))

        log = {"audit_type": "request", "data": {"x": 1}}
        auditor.add_log(log)

        storage.store_log.assert_called_once_with(
            audit_log=log, audit_type="request"
        )

    def test_add_log_emits_warning_with_audit_type(self, monkeypatch):
        monkeypatch.setattr(
            auditor_module, "DEFAULT_AUDITOR_STORAGE_CLASS", lambda: mock.Mock()
        )
        logger = mock.Mock(spec=logging.Logger)
        auditor = AnyRequestAuditor(logger)

        auditor.add_log({"audit_type": "auth_event"})
        logger.warning.assert_called_once()
        args = logger.warning.call_args[0]
        assert "auth_event" in args[0]

    def test_add_log_missing_audit_type_raises_key_error(self, monkeypatch):
        monkeypatch.setattr(
            auditor_module, "DEFAULT_AUDITOR_STORAGE_CLASS", lambda: mock.Mock()
        )
        auditor = AnyRequestAuditor(logging.getLogger("test"))
        with pytest.raises(KeyError):
            auditor.add_log({"something": "else"})

    def test_storage_instance_created_from_default_class(self, monkeypatch):
        created = []

        def _factory():
            instance = mock.Mock()
            created.append(instance)
            return instance

        monkeypatch.setattr(
            auditor_module, "DEFAULT_AUDITOR_STORAGE_CLASS", _factory
        )
        auditor = AnyRequestAuditor(logging.getLogger("test"))
        assert auditor._auditor_storage is created[0]


class TestAuditorLogStorageInterface:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            AuditorLogStorageInterface()

    def test_abstract_store_log_requires_implementation(self):
        with pytest.raises(TypeError):

            class Incomplete(AuditorLogStorageInterface):
                pass

            Incomplete()

    def test_concrete_subclass_works(self):
        class Complete(AuditorLogStorageInterface):
            def store_log(self, audit_log, audit_type: str) -> None:
                self.stored = (audit_log, audit_type)

        instance = Complete()
        instance.store_log({"a": 1}, "request")
        assert instance.stored == ({"a": 1}, "request")
