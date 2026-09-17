"""
Tests for the ``llm-router completion`` command (bash / zsh tab-completion).
"""

from __future__ import annotations

import shlex
import subprocess

from typing import List

from llm_router_cli.cli import main
from llm_router_cli.cli.commands.completion import (
    CompletionCommand,
    _command_tree,
)


def _script(shell: str, capsys) -> str:
    assert main(["completion", shell]) == 0
    return capsys.readouterr().out


def _bash_completions(script: str, words: List[str], tmp_path) -> List[str]:
    """Run the generated bash function for *words* and return ``COMPREPLY``."""
    completion_file = tmp_path / "llm-router-completion.bash"
    completion_file.write_text(script, encoding="utf-8")
    probe = tmp_path / "probe.bash"
    probe.write_text(
        "\n".join(
            [
                f"source {shlex.quote(str(completion_file))}",
                "COMP_WORDS=( {} )".format(
                    " ".join(shlex.quote(word) for word in words)
                ),
                f"COMP_CWORD={len(words) - 1}",
                "COMPREPLY=()",
                "_llm-router",
                "printf '%s\\n' \"${COMPREPLY[@]}\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(probe)], capture_output=True, text=True, check=True
    )
    return result.stdout.split()


def test_completion_bash_lists_commands_subcommands_options(capsys):
    out = _script("bash", capsys)
    assert "complete -F _llm-router llm-router" in out
    # Top-level commands.
    assert "'auth' 'anonymizer' 'config' 'completion' 'server' 'util'" in out
    # Second-level subcommands (server, auth).
    assert (
        "subs=( 'start' 'stop' 'reload' 'status' 'log' 'list' 'rm-instance' )" in out
    )
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
    assert "'--instance'" in out  # every server sub-command
    assert "'--no-port-check'" in out  # server start
    assert "'--no-config-check'" in out  # server start
    assert "'-i'" in out  # short form of --instance
    assert "'-o'" in out  # short form of --output / --output-config-file


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
    assert "'-i'" in out  # short form of --instance
    assert "'-o'" in out  # short form of --output / --output-config-file


def test_completion_no_shell_prints_help(capsys):
    assert CompletionCommand.run(["completion"]) == 0
    out = capsys.readouterr().out
    assert "bash" in out and "zsh" in out


def test_bash_script_has_valid_syntax(capsys):
    script = _script("bash", capsys)
    subprocess.run(["bash", "-nc", script], check=True)


# --------------------------------------------------------------------------- #
# generated bash function (behaviour)
# --------------------------------------------------------------------------- #


def test_bash_completes_long_and_short_options(capsys, tmp_path):
    script = _script("bash", capsys)
    longs = _bash_completions(
        script, ["llm-router", "server", "start", "--"], tmp_path
    )
    assert "--instance" in longs
    assert "-i" not in longs  # `-i` does not start with `--`
    assert "-i" in _bash_completions(
        script, ["llm-router", "server", "start", "-"], tmp_path
    )


def test_bash_keeps_options_after_values(capsys, tmp_path):
    script = _script("bash", capsys)
    words = ["llm-router", "server", "start", "--port", "8081", ""]
    cands = _bash_completions(script, words, tmp_path)
    assert "--save-config" in cands
    assert "--instance" in cands
    assert "-i" in cands


def test_bash_completes_deep_subcommands_and_their_options(capsys, tmp_path):
    script = _script("bash", capsys)
    assert "generate" in _bash_completions(
        script, ["llm-router", "auth", "key", ""], tmp_path
    )
    assert "--policy" in _bash_completions(
        script, ["llm-router", "auth", "key", "generate", "--"], tmp_path
    )
    assert _bash_completions(
        script, ["llm-router", "server", "stop", "--insta"], tmp_path
    ) == ["--instance"]
    assert "-o" in _bash_completions(
        script, ["llm-router", "util", "translate", "-"], tmp_path
    )


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
    assert set(tree["server"]["subs"]) == {
        "start",
        "stop",
        "reload",
        "status",
        "log",
        "list",
        "rm-instance",
    }
    assert "--force" in tree["server"]["subs"]["stop"]["options"]
    assert "--all" in tree["server"]["subs"]["stop"]["options"]
    assert "--instance" in tree["server"]["subs"]["status"]["options"]
    assert "-i" in tree["server"]["subs"]["status"]["options"]
    # Long options are proposed before their short counterpart.
    stop_options = tree["server"]["subs"]["stop"]["options"]
    assert stop_options.index("--instance") < stop_options.index("-i")
    assert "--json" in tree["server"]["subs"]["list"]["options"]
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
    assert "-o" in tree["anonymizer"]["subs"]["run"]["options"]
    assert "-o" in tree["config"]["subs"]["merge"]["options"]
    assert "-o" in tree["util"]["subs"]["translate"]["options"]


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
    rc.write_text(
        "echo before\n{}\nSTALE-BLOCK\n{}\necho after\n".format(begin, end)
    )
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
    assert main(["completion", "bash", "--install", "--file", str(target)]) == 0
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
