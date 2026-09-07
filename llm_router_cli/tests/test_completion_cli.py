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
    assert 'subs="auth anonymizer config completion server util"' in out
    assert "start stop reload status log" in out
    assert "bash zsh" in out
    assert "--redis-host" in out
    assert "--no-follow" in out
    assert "--models-config" in out
    assert "--lb-strategy" in out


def test_completion_zsh_lists_commands_subcommands_options(capsys):
    out = _script("zsh", capsys)
    assert out.splitlines()[0] == "#compdef llm-router"
    assert "auth anonymizer config completion server util" in out
    assert "'start'" in out
    assert "'--redis-host'" in out
    assert "'--no-follow'" in out
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
    assert set(tree["server"]) == {"start", "stop", "reload", "status", "log"}
    assert "--force" in tree["server"]["stop"]
    assert "--color" in tree["server"]["log"]
    assert "--models-config" in tree["server"]["start"]
