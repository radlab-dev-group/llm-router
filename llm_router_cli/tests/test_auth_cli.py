"""
Tests for the ``llm-router auth`` CLI command.

Covers the single-parse dispatch (no argv re-scanning), the key lifecycle
(generate / list / rotate / disable / enable / delete), rate-limit preset
apply / remove across the store backends, and the Vault kwargs wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_router_cli.cli.commands.auth import AuthCommand


def _read_seed(seed_file: str) -> list:
    return json.loads(Path(seed_file).read_text(encoding="utf-8"))


def _active_key_id(seed_file: str) -> str:
    recs = _read_seed(seed_file)
    active = [r for r in recs if r.get("is_active")]
    assert active, f"expected an active key in {seed_file}"
    return active[0]["key_id"]


# ---- help / dispatch ----------------------------------------------------


def test_help_rc0(auth_home, capsys):
    assert AuthCommand.run([]) == 0
    out = capsys.readouterr().out
    assert "key" in out and "policy" in out and "rate-limit" in out


def test_key_without_subcommand_fails(auth_home, capsys):
    assert AuthCommand.run(["key"]) == 1


def test_rate_limit_list(auth_home, capsys):
    assert AuthCommand.run(["rate-limit", "list"]) == 0
    out = capsys.readouterr().out
    assert "free" in out and "pro" in out


def test_policy_list(auth_home, capsys):
    assert AuthCommand.run(["policy", "list"]) == 0
    out = capsys.readouterr().out
    assert "developer" in out


# ---- key generate -------------------------------------------------------


def test_generate_default_policy(auth_home, capsys):
    assert AuthCommand.run(["key", "generate"]) == 0
    recs = _read_seed(auth_home)
    assert len(recs) == 1
    assert recs[0]["policy_name"] == "developer"
    assert recs[0]["key_hash"], "plaintext must never be persisted"


def test_generate_with_expires(auth_home, capsys):
    assert AuthCommand.run(["key", "generate", "--expires", "1800000000"]) == 0
    recs = _read_seed(auth_home)
    assert recs[0]["expires_at"] == 1800000000.0


def test_generate_bad_expires_fails(auth_home, capsys):
    assert AuthCommand.run(["key", "generate", "--expires", "not-a-number"]) == 1


def test_generate_unknown_policy_fails(auth_home, capsys):
    assert AuthCommand.run(["key", "generate", "--policy", "does-not-exist"]) == 1


def test_generate_output_file(auth_home, tmp_path, capsys):
    out = tmp_path / "key.txt"
    assert AuthCommand.run(["key", "generate", "--output", str(out)]) == 0
    key = out.read_text(encoding="utf-8").strip()
    assert key.startswith("sk-")
    captured = capsys.readouterr().out
    assert str(out) in captured
    assert key not in captured, "full key must not be echoed to stdout with --output"


# ---- key list -----------------------------------------------------------


def test_list_empty(auth_home, capsys):
    assert AuthCommand.run(["key", "list"]) == 0
    assert "No API keys found." in capsys.readouterr().out


def test_list_table_and_json(auth_home, capsys):
    assert AuthCommand.run(["key", "generate"]) == 0
    capsys.readouterr()

    assert AuthCommand.run(["key", "list"]) == 0
    out = capsys.readouterr().out
    assert "KEY_ID" in out and "POLICY" in out

    assert AuthCommand.run(["key", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["key_id"]


# ---- key rotate / disable / enable / delete -----------------------------


def test_rotate(auth_home, capsys):
    AuthCommand.run(["key", "generate"])
    kid = _active_key_id(auth_home)
    assert AuthCommand.run(["key", "rotate", kid]) == 0
    recs = _read_seed(auth_home)
    old = [r for r in recs if r["key_id"] == kid][0]
    assert old["is_active"] is False, "old key must be deactivated on rotate"
    # A new active key id must have been created (``<kid>-rotated-<ts>``).
    new_active = [r for r in recs if r.get("is_active") and r["key_id"] != kid]
    assert len(new_active) == 1
    assert new_active[0]["key_id"].startswith(kid + "-rotated-")


def test_rotate_missing_key_fails(auth_home, capsys):
    assert AuthCommand.run(["key", "rotate", "no-such-key"]) == 1


def test_disable_enable(auth_home, capsys):
    AuthCommand.run(["key", "generate"])
    kid = _active_key_id(auth_home)

    assert AuthCommand.run(["key", "disable", kid]) == 0
    assert _read_seed(auth_home)[0]["is_active"] is False

    assert AuthCommand.run(["key", "enable", kid]) == 0
    assert _read_seed(auth_home)[0]["is_active"] is True


def test_disable_missing_key_fails(auth_home, capsys):
    assert AuthCommand.run(["key", "disable", "no-such-key"]) == 1


def test_delete(auth_home, capsys):
    AuthCommand.run(["key", "generate"])
    kid = _active_key_id(auth_home)
    assert AuthCommand.run(["key", "delete", kid]) == 0
    assert _read_seed(auth_home) == []


# ---- rate-limit apply / remove (memory store) ---------------------------


def test_rate_limit_apply_and_remove(auth_home, capsys):
    AuthCommand.run(["key", "generate"])
    kid = _active_key_id(auth_home)

    assert AuthCommand.run(["rate-limit", "apply", kid, "--preset", "pro"]) == 0
    rec = [r for r in _read_seed(auth_home) if r["key_id"] == kid][0]
    assert rec["policy_override"] == {"rate_limit": 120}

    assert AuthCommand.run(["rate-limit", "remove", kid]) == 0
    rec = [r for r in _read_seed(auth_home) if r["key_id"] == kid][0]
    assert rec.get("policy_override") in (None, {})


def test_rate_limit_apply_unknown_preset_fails(auth_home, capsys):
    AuthCommand.run(["key", "generate"])
    kid = _active_key_id(auth_home)
    assert AuthCommand.run(["rate-limit", "apply", kid, "--preset", "nope"]) == 1


def test_rate_limit_apply_missing_key_fails(auth_home, capsys):
    assert (
        AuthCommand.run(["rate-limit", "apply", "no-such-key", "--preset", "pro"])
        == 1
    )


def test_rate_limit_remove_missing_key_fails(auth_home, capsys):
    assert AuthCommand.run(["rate-limit", "remove", "no-such-key"]) == 1


# ---- policy create ------------------------------------------------------


def test_policy_create_valid(auth_home, capsys):
    from llm_router_api.core.auth.policies import builtin

    rc = AuthCommand.run(
        [
            "policy",
            "create",
            "myteam",
            json.dumps(
                {"can_access": True, "allowed_types": ["chat"], "rate_limit": 30}
            ),
        ]
    )
    assert rc == 0
    assert "created" in capsys.readouterr().out
    # do not leak the custom policy into other tests
    builtin._builtin_policies.pop("myteam", None)


def test_policy_create_bad_json_fails(auth_home, capsys):
    assert AuthCommand.run(["policy", "create", "myteam", "{not json"]) == 1


# ---- vault kwargs wiring ------------------------------------------------


def test_vault_requires_addr(monkeypatch, auth_home, capsys):
    monkeypatch.delenv("LLM_ROUTER_AUTH_VAULT_ADDR", raising=False)
    assert AuthCommand.run(["key", "generate", "--store", "vault"]) == 1
    assert "LLM_ROUTER_AUTH_VAULT_ADDR" in capsys.readouterr().err


def test_vault_kwargs_passed_to_factory(monkeypatch, auth_home):
    import llm_router_api.core.auth.key_store as ks

    monkeypatch.setenv("LLM_ROUTER_AUTH_VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("LLM_ROUTER_AUTH_VAULT_PATH", "secret/data/keys")
    monkeypatch.setenv("LLM_ROUTER_AUTH_VAULT_AUTH_METHOD", "approle")
    monkeypatch.setenv("LLM_ROUTER_AUTH_VAULT_ROLE_ID", "role-1")
    monkeypatch.setenv("LLM_ROUTER_AUTH_VAULT_SECRET_ID", "sec-1")

    captured = {}

    class _FakeStore:
        async def create_key(self, record):
            return "sk-vault-fake"

    def _fake_factory(store_type="memory", **kwargs):
        captured["store_type"] = store_type
        captured["kwargs"] = kwargs
        return _FakeStore(), None

    monkeypatch.setattr(ks, "create_key_store", _fake_factory)

    assert AuthCommand.run(["key", "generate", "--store", "vault"]) == 0
    assert captured["store_type"] == "vault"
    assert captured["kwargs"] == {
        "addr": "http://vault:8200",
        "mount_path": "secret/data/keys",
        "auth_method": "approle",
        "role_id": "role-1",
        "secret_id": "sec-1",
    }


# ---- top-level main() single-parse entry point --------------------------


def test_main_dispatches_auth(auth_home, capsys):
    from llm_router_cli.cli import main

    assert main(["auth", "key", "generate"]) == 0
    capsys.readouterr()
    assert main(["auth", "key", "list"]) == 0
    assert main(["auth", "rate-limit", "list"]) == 0
    assert main([]) == 0
