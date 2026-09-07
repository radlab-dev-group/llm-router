"""
Tests for the ``llm-router completion`` command (bash / zsh tab-completion).
"""

from __future__ import annotations

import subprocess

from llm_router_cli.cli import main
from llm_router_cli.cli.commands.completion import (
    CompletionCommand,
    _command_tree,
    _render_bash,
    _render_zsh,
)


def _script(shell: str, capsys) -> str:
    assert main(["completion", shell]) == 0
    return capsys.readouterr().out


def test_completion_bash_lists_commands_subcommands_options(capsys):
    out = _script("bash", capsys)
    assert "complete -F _llm-router llm-router" in out
    # Top-level commands.
    assert "'auth' 'anonymizer' 'config' 'completion' 'server' 'util'" in out
    # Second-level subcommands (server, auth).
    assert "subs=( 'start' 'stop' 'reload' 'status' 'log' )" in out
    assert "subs=( 'key' 'policy' 'rate-limit' )" in out
    # Third-level subcommands are present as full paths in the tree.
    assert "'auth key generate'" in out
    assert "'auth key'" in out
    assert "'anonymizer run'" in out
    assert "'config discover'" in out
    # Options at every level, including deep ones.
    assert "--redis-host" in out
    assert "--no-follow" in out
    assert "--models-config" in out
    assert "--lb-strategy" in out
    assert "--show-env" in out
    assert "'--auth-redis-host'" in out  # auth key * options (level 3)
    assert "'--preset'" in out  # auth rate-limit apply (level 3)
    assert "'--algorithm'" in out  # anonymizer run (level 2)
    assert "'--output-config-file'" in out  # config discover/merge (level 2)
    assert "'--install'" in out  # completion bash/zsh (level 2)


def test_completion_zsh_lists_commands_subcommands_options(capsys):
    out = _script("zsh", capsys)
    assert out.splitlines()[0] == "#compdef llm-router"
    assert "'auth' 'anonymizer' 'config' 'completion' 'server' 'util'" in out
    assert "'auth key generate'" in out
    assert "'auth key'" in out
    assert "'start'" in out
    assert "'--redis-host'" in out
    assert "'--no-follow'" in out
    assert "'--auth-redis-host'" in out
    assert "'--preset'" in out
    assert "'--algorithm'" in out
    assert "compdef _llm-router llm-router" in out


def test_completion_no_shell_prints_help(capsys):
    assert CompletionCommand.run(["completion"]) == 0
    out = capsys.readouterr().out
    assert "bash" in out and "zsh" in out


def test_bash_script_has_valid_syntax(capsys):
    script = _script("bash", capsys)
    subprocess.run(["bash", "-nc", script], check=True)


def test_command_tree_matches_registered_commands():
    tree = _command_tree(CompletionCommand._top_parser())
    assert set(tree) == {
        "auth",
        "anonymizer",
        "config",
        "completion",
        "server",
        "util",
    }
    # Second level.
    assert set(tree["server"]["subs"]) == {"start", "stop", "reload", "status", "log"}
    assert "--force" in tree["server"]["subs"]["stop"]["options"]
    assert "--color" in tree["server"]["subs"]["log"]["options"]
    assert "--models-config" in tree["server"]["subs"]["start"]["options"]
    # Third level: auth key *.
    assert set(tree["auth"]["subs"]["key"]["subs"]) == {
        "generate",
        "list",
        "delete",
        "disable",
        "enable",
        "rotate",
    }
    assert "--policy" in tree["auth"]["subs"]["key"]["subs"]["generate"]["options"]
    assert "--json" in tree["auth"]["subs"]["key"]["subs"]["list"]["options"]
    # Second level with no third level.
    assert tree["anonymizer"]["subs"]["run"]["subs"] == {}
    assert "--algorithm" in tree["anonymizer"]["subs"]["run"]["options"]


# --------------------------------------------------------------------------- #
# --install
# --------------------------------------------------------------------------- #

def test_install_bash_writes_default_rc(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["completion", "bash", "--install"]) == 0
    out = capsys.readouterr().out
    rc = tmp_path / ".bashrc"
    assert rc.is_file()
    content = rc.read_text()
    assert "# >>> llm-router completion (bash) >>>" in content
    assert "# <<< llm-router completion (bash) <<<" in content
    assert "complete -F _llm-router llm-router" in content
    assert str(rc) in out
    assert "source" in out
    # The script itself must not be dumped to stdout.
    assert "compgen" not in out


def test_install_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    for _ in range(2):
        assert main(["completion", "bash", "--install"]) == 0
        capsys.readouterr()
    content = (tmp_path / ".bashrc").read_text()
    assert content.count("# >>> llm-router completion (bash) >>>") == 1
    assert content.count("complete -F _llm-router llm-router") == 1


def test_install_replaces_stale_block(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = tmp_path / ".bashrc"
    begin = "# >>> llm-router completion (bash) >>>"
    end = "# <<< llm-router completion (bash) <<<"
    rc.write_text("echo before\n{}\nSTALE-BLOCK\n{}\necho after\n".format(begin, end))
    assert main(["completion", "bash", "--install"]) == 0
    capsys.readouterr()
    content = rc.read_text()
    assert "STALE-BLOCK" not in content
    assert content.count(begin) == 1
    assert "echo before" in content
    assert "echo after" in content
    assert "complete -F _llm-router llm-router" in content


def test_install_custom_file(tmp_path, capsys):
    target = tmp_path / "custom-rc"
    assert main(
        ["completion", "bash", "--install", "--file", str(target)]
    ) == 0
    capsys.readouterr()
    assert target.is_file()
    assert "complete -F _llm-router llm-router" in target.read_text()


def test_install_zsh_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["completion", "zsh", "--install"]) == 0
    capsys.readouterr()
    rc = tmp_path / ".zshrc"
    assert rc.is_file()
    content = rc.read_text()
    assert content.count("# >>> llm-router completion (zsh) >>>") == 1
    assert "#compdef llm-router" in content
    assert "compdef _llm-router llm-router" in content


def test_install_write_failure_returns_error(tmp_path, capsys):
    target = tmp_path / "no-such-dir" / "rc"
    rc = main(["completion", "bash", "--install", "--file", str(target)])
    out = capsys.readouterr()
    assert rc != 0
    assert "could not install" in out.err
    assert str(target) in out.err
    assert not target.exists()
