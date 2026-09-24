"""
Tests for the ``llm-router completion`` command (bash / zsh tab-completion).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

from typing import List, Optional

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands.completion import (
    CompletionCommand,
    _command_tree,
    _collect_by_path,
    _merge_option_kinds,
    _merge_option_values,
    _paths_by_positional,
)

HAS_ZSH = shutil.which("zsh") is not None


def _script(shell: str, capsys) -> str:
    assert main(["completion", shell]) == 0
    return capsys.readouterr().out


def _home_env(home: Optional[str]) -> Optional[dict]:
    """Probe environment with ``HOME`` pinned (``None`` = inherit)."""
    return None if home is None else {**os.environ, "HOME": home}


def _bash_completions(
    script: str,
    words: List[str],
    tmp_path,
    home: Optional[str] = None,
    cwd: Optional[str] = None,
) -> List[str]:
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
        ["bash", str(probe)],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=_home_env(home),
    )
    return result.stdout.split()


def _zsh_completions(
    script: str,
    words: List[str],
    tmp_path,
    home: Optional[str] = None,
    cwd: Optional[str] = None,
) -> List[str]:
    """
    Run the generated zsh function for *words* and return its candidates.

    ``compadd`` and ``_files`` (a compinit widget) are replaced by the two
    things the completion function really needs from them: a place to put
    the candidates and a listing of the current directory.
    """
    completion_file = tmp_path / "llm-router-completion.zsh"
    completion_file.write_text(script, encoding="utf-8")
    probe = tmp_path / "probe.zsh"
    probe.write_text(
        "\n".join(
            [
                f"source {shlex.quote(str(completion_file))}",
                "compadd() {",
                '  if [[ "$1" == "-a" ]]; then',
                "    local candidate",
                '    for candidate in ${(P)2}; do print -r -- "$candidate"; done',
                "  fi",
                "  return 0",
                "}",
                "_files() {",
                '  local file prefix="${words[CURRENT]}"',
                "  for file in *(N); do",
                '    [[ "$file" == "${prefix}"* ]] && print -r -- "$file"',
                "  done",
                "  return 0",
                "}",
                "words=( {} )".format(" ".join(shlex.quote(word) for word in words)),
                # ``words`` is 1-based in zsh and includes the command name.
                "CURRENT={}".format(len(words)),
                "_llm-router",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["zsh", str(probe)],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=_home_env(home),
    )
    assert not result.stderr.strip(), result.stderr
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


# --------------------------------------------------------------------------- #
# completeness: both scripts mirror the registered parser tree
# --------------------------------------------------------------------------- #


def _rendered_case(script: str) -> dict:
    """The ``case`` clauses of a generated script, ``path -> options/subs``."""
    rendered: dict = {}
    current = None
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith('"') and stripped.endswith(")"):
            current = stripped[1:-2]
            rendered[current] = {"options": [], "subs": []}
        elif stripped.startswith("opts=(") and current is not None:
            rendered[current]["options"] = re.findall(r"'([^']*)'", stripped)
        elif stripped.startswith("subs=(") and current is not None:
            rendered[current]["subs"] = re.findall(r"'([^']*)'", stripped)
    return rendered


def _expected_case() -> dict:
    """Every registered command path with its options and sub-commands."""
    tree = _command_tree(CompletionCommand._top_parser())
    return {
        path: {"options": info["options"], "subs": list(info["subs"])}
        for path, info in _collect_by_path(tree).items()
    }


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_script_covers_every_command_sub_command_and_option(shell, capsys):
    out = _script(shell, capsys)
    rendered, expected = _rendered_case(out), _expected_case()
    assert rendered, "the generated script has no command clauses"
    assert set(rendered) == set(expected)
    for path, wanted in expected.items():
        assert rendered[path]["options"] == wanted["options"], path
        assert set(rendered[path]["subs"]) == set(wanted["subs"]), path


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_script_lists_the_top_level_options(shell, capsys):
    assert "_LR_ROOT_OPTS=( '--version' )" in _script(shell, capsys)


def test_every_option_has_a_completion_kind():
    tree = _command_tree(CompletionCommand._top_parser())
    kinds = _merge_option_kinds(tree)
    for path, info in _collect_by_path(tree).items():
        for opt in info["options"]:
            assert opt in kinds, f"{opt} of '{path}' has no completion kind"
    assert kinds["--force"] == kinds["--graceful"] == kinds["--verbose"] == "flag"
    assert kinds["--color"] == kinds["--store"] == kinds["--debug"] == "choice"
    assert kinds["-i"] == kinds["--instance"] == "instance"
    assert kinds["-o"] == kinds["--log-file"] == kinds["--output-dir"] == "path"
    assert kinds["--host"] == kinds["--port"] == "value"


def test_option_choices_are_complete_and_unambiguous():
    tree = _command_tree(CompletionCommand._top_parser())
    values = _merge_option_values(tree)
    assert values["--color"] == ["auto", "always", "never"]
    assert values["--store"] == ["memory", "redis", "vault"]
    assert values["--algorithm"] == ["fast_masker", "pii"]
    assert set(values["--lb-strategy"]) == {
        "balanced",
        "weighted",
        "first_available",
        "first_available_optim",
        "first_available_optim_nworkers",
    }
    seen: dict = {}
    for path, info in _collect_by_path(tree).items():
        for opt, accepted in info["values"].items():
            assert (
                seen.setdefault(opt, accepted) == accepted
            ), f"{opt} declares different choices under '{path}'"


def test_positional_arguments_are_classified():
    tree = _command_tree(CompletionCommand._top_parser())
    files = _paths_by_positional(tree, "file")
    assert files == ["anonymizer run", "config merge"]
    assert _paths_by_positional(tree, "instance") == ["server rm-instance"]
    # hosts and key ids are not files, and must not be completed as such
    assert "config discover" not in files
    assert "auth key delete" not in files


# --------------------------------------------------------------------------- #
# values, instances and file names (behaviour)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "words, expected",
    [
        (["llm-router", "--"], ["--version"]),
        (["llm-router", "s"], ["server"]),
        (["llm-router", "server", "reload", "--g"], ["--graceful"]),
        (["llm-router", "auth", "key", "rotate", "--g"], ["--grace"]),
        (
            ["llm-router", "server", "status", "--color", ""],
            ["auto", "always", "never"],
        ),
        (
            ["llm-router", "util", "translate", "--dataset-type", "j"],
            ["json", "jsonl"],
        ),
        (["llm-router", "anonymizer", "run", "--algorithm", "p"], ["pii"]),
        (["llm-router", "server", "start", "--debug", "1"], ["1"]),
    ],
)
def test_bash_completes_root_options_options_and_values(
    capsys, tmp_path, words, expected
):
    script = _script("bash", capsys)
    assert _bash_completions(script, words, tmp_path) == expected


def test_bash_completes_instance_names(capsys, tmp_path):
    script = _script("bash", capsys)
    home = tmp_path / "home"
    for name in ("dev", "staging"):
        (home / ".llm-router" / "instances" / name).mkdir(parents=True)
    for words in (
        ["llm-router", "server", "stop", "-i", ""],
        ["llm-router", "server", "rm-instance", ""],
    ):
        candidates = _bash_completions(script, words, tmp_path, home=str(home))
        assert candidates == ["default", "dev", "staging"]


def test_bash_completes_file_arguments_and_path_options(capsys, tmp_path):
    script = _script("bash", capsys)
    work = tmp_path / "work"
    work.mkdir()
    (work / "models-config.json").write_text("{}", encoding="utf-8")
    merged = _bash_completions(
        script,
        ["llm-router", "config", "merge", ""],
        tmp_path,
        cwd=str(work),
    )
    assert "models-config.json" in merged
    assert "-o" in merged  # the options are offered alongside the files
    assert _bash_completions(
        script,
        ["llm-router", "server", "start", "--models-config", ""],
        tmp_path,
        cwd=str(work),
    ) == ["models-config.json"]


def test_bash_does_not_offer_files_for_non_path_arguments(capsys, tmp_path):
    script = _script("bash", capsys)
    work = tmp_path / "work"
    work.mkdir()
    (work / "models-config.json").write_text("{}", encoding="utf-8")
    for words in (
        ["llm-router", "config", "discover", ""],  # <hosts>
        ["llm-router", "auth", "key", "delete", ""],  # <key-id>
    ):
        candidates = _bash_completions(script, words, tmp_path, cwd=str(work))
        assert candidates, words
        assert "models-config.json" not in candidates, words


@pytest.mark.skipif(not HAS_ZSH, reason="zsh is not installed")
def test_zsh_script_has_valid_syntax(capsys):
    subprocess.run(["zsh", "-nc", _script("zsh", capsys)], check=True)


@pytest.mark.skipif(not HAS_ZSH, reason="zsh is not installed")
def test_zsh_function_completes_commands_sub_commands_and_options(capsys, tmp_path):
    """The zsh function has to *run*: a broken expansion yields no candidates."""
    script = _script("zsh", capsys)
    commands = _zsh_completions(script, ["llm-router", ""], tmp_path)
    assert "server" in commands
    assert "--version" in commands
    # ``compadd`` filters by the typed prefix in a real shell; the stub below
    # only reports what the function handed over, so membership is checked.
    server = _zsh_completions(script, ["llm-router", "server", ""], tmp_path)
    assert {
        "start",
        "stop",
        "reload",
        "status",
        "log",
        "list",
        "rm-instance",
    } <= set(server)
    stop = _zsh_completions(script, ["llm-router", "server", "stop", ""], tmp_path)
    assert {"--force", "--all", "--instance", "-i"} <= set(stop)
    key = _zsh_completions(script, ["llm-router", "auth", "key", ""], tmp_path)
    assert "rotate" in key


@pytest.mark.skipif(not HAS_ZSH, reason="zsh is not installed")
def test_zsh_completes_choices_instances_and_files(capsys, tmp_path):
    script = _script("zsh", capsys)
    home = tmp_path / "home"
    for name in ("dev", "staging"):
        (home / ".llm-router" / "instances" / name).mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (work / "models-config.json").write_text("{}", encoding="utf-8")
    assert _zsh_completions(
        script, ["llm-router", "server", "status", "--color", ""], tmp_path
    ) == ["auto", "always", "never"]
    assert _zsh_completions(
        script, ["llm-router", "server", "stop", "-i", ""], tmp_path, home=str(home)
    ) == ["default", "dev", "staging"]
    assert _zsh_completions(
        script,
        ["llm-router", "server", "rm-instance", ""],
        tmp_path,
        home=str(home),
    ) == ["default", "dev", "staging"]
    merged = _zsh_completions(
        script, ["llm-router", "config", "merge", ""], tmp_path, cwd=str(work)
    )
    assert "models-config.json" in merged
    assert "--verbose" in merged
    assert _zsh_completions(
        script,
        ["llm-router", "server", "start", "--pid-file", ""],
        tmp_path,
        cwd=str(work),
    ) == ["models-config.json"]


@pytest.mark.skipif(not HAS_ZSH, reason="zsh is not installed")
def test_zsh_does_not_offer_files_for_non_path_arguments(capsys, tmp_path):
    script = _script("zsh", capsys)
    work = tmp_path / "work"
    work.mkdir()
    (work / "models-config.json").write_text("{}", encoding="utf-8")
    for words in (
        ["llm-router", "config", "discover", ""],  # <hosts>
        ["llm-router", "auth", "key", "delete", ""],  # <key-id>
    ):
        candidates = _zsh_completions(script, words, tmp_path, cwd=str(work))
        assert candidates, words
        assert "models-config.json" not in candidates, words


def test_no_option_declares_conflicting_kinds():
    """An option name must complete the same way everywhere it is offered."""
    tree = _command_tree(CompletionCommand._top_parser())
    seen: dict = {}
    for path, info in _collect_by_path(tree).items():
        for opt, kind in info["kinds"].items():
            assert (
                seen.setdefault(opt, kind) == kind
            ), f"{opt} is a '{seen[opt]}' elsewhere but a '{kind}' under '{path}'"


def test_store_const_options_are_flags():
    """``server start --verbose`` is a ``store_const`` — it takes no value."""
    tree = _command_tree(CompletionCommand._top_parser())
    assert _collect_by_path(tree)["server start"]["kinds"]["--verbose"] == "flag"


def test_bash_keeps_offering_options_after_a_flag(capsys, tmp_path):
    script = _script("bash", capsys)
    for words in (
        ["llm-router", "server", "start", "--verbose", ""],
        ["llm-router", "server", "reload", "--force", ""],
    ):
        after_flag = _bash_completions(script, words, tmp_path)
        assert "--pid-file" in after_flag, words
        assert "-i" in after_flag, words
