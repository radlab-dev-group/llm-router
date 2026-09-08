"""
Shell tab-completion for ``llm-router`` (bash and zsh).

The script is generated from the *live* top-level parser, so completions
always match the registered commands, sub-commands and long options::

    # bash — append to ~/.bashrc (or run once per shell):
    eval "$(llm-router completion bash)"

    # zsh — append to ~/.zshrc:
    source <(llm-router completion zsh)

Or install directly into the default rc file (``~/.bashrc`` / ``~/.zshrc``),
replacing any previous install on re-run::

    llm-router completion bash --install
    llm-router completion zsh --install --file ~/.config/zsh/completion.zsh
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path
from typing import Any, ClassVar, Dict, List, Tuple

from llm_router_cli.cli.commands.base import BaseCommand


def _long_options(parser: argparse.ArgumentParser) -> List[str]:
    """All long (``--``) option strings declared on *parser* (no sub-commands)."""
    opts: List[str] = []
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        for opt in action.option_strings:
            if opt.startswith("--") and opt not in opts:
                opts.append(opt)
    return opts


def _command_tree(
    parser: argparse.ArgumentParser,
) -> Dict[str, Dict[str, Any]]:
    """
    Recursively extract the command tree from *parser*.

    Every node maps ``name -> {"options": [...], "subs": {name: node}}``
    so any nesting depth (e.g. ``auth key generate``) is captured.
    """
    tree: Dict[str, Dict[str, Any]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            if name == "help" or sub is None:
                continue
            tree[name] = {
                "options": _long_options(sub),
                "subs": _command_tree(sub),
            }
    return tree


def _flatten_paths(
    tree: Dict[str, Dict[str, Any]],
) -> Dict[str, Tuple[List[str], List[str]]]:
    """
    Flatten *tree* into ``"cmd sub ..." -> (options, subcommands)``.

    Ordered by path depth (parents before children) so the rendered case
    statements read top-down.
    """
    paths: Dict[str, Tuple[List[str], List[str]]] = {}

    def rec(node: Dict[str, Any], prefix: Tuple[str, ...]) -> None:
        for name, info in node.items():
            p = prefix + (name,)
            paths[" ".join(p)] = (list(info["options"]), list(info["subs"]))
            rec(info["subs"], p)

    rec(tree, ())
    return {
        p: v
        for p, v in sorted(paths.items(), key=lambda kv: (-len(kv[0].split()), kv[0]))
    }


def _path_case_lines(
    paths: Dict[str, Tuple[List[str], List[str]]], indent: str
) -> List[str]:
    """Render the shared ``case "${matched}"`` clauses for one shell."""
    lines: List[str] = [
        indent + 'case "${matched}" in',
    ]
    for p, (opts, subs) in paths.items():
        lines.append(f'{indent}    "{p}")')
        if opts:
            lines.append(
                indent
                + "        opts=( {} )".format(" ".join(f"'{o}'" for o in opts))
            )
        if subs:
            lines.append(
                indent
                + "        subs=( {} )".format(" ".join(f"'{s}'" for s in subs))
            )
        lines.append(f"{indent}    ;;")
    lines.append(f"{indent}    *)")
    lines.append(f"{indent}        ;;")
    lines.append(f"{indent}    esac")
    return lines


def _render_bash(tree: Dict[str, Dict[str, Any]]) -> str:
    """Render a bash completion function from *tree* (any nesting depth)."""
    paths = _flatten_paths(tree)
    lines: List[str] = [
        "# Tab completion for llm-router (bash).",
        '# Install: eval "$(llm-router completion bash)"   # or append to ~/.bashrc',
        "_LR_PATHS=( {} )".format(" ".join(f"'{p}'" for p in paths)),
        "_LR_ROOT=( {} )".format(" ".join(f"'{n}'" for n in tree)),
        "_llm-router() {",
        '    local cur="${COMP_WORDS[COMP_CWORD]}"',
        "    local i p typed matched",
        "    local -a c=() cands=() opts=() subs=()",
        "    i=1",
        "    while (( i < COMP_CWORD )); do",
        '        c+=("${COMP_WORDS[i]}")',
        "        i=$(( i + 1 ))",
        "    done",
        '    typed="${c[*]}"',
        '    typed="${typed%"${typed##*[! ]}"}"',
        '    if [[ -z "${typed}" ]]; then',
        "        cands=( ${_LR_ROOT[@]} )",
        "    else",
        "        for p in \"${_LR_PATHS[@]}\"; do",
        '            if [[ "${typed}" == "${p}" || "${typed}" == "${p} "* ]]; then',
        '                matched="${p}"',
        "                break",
        "            fi",
        "        done",
    ]
    lines.extend(_path_case_lines(paths, "        "))
    lines += [
        "        cands=( ${subs[@]} )",
        '        if [[ -n "${matched}" && "${typed}" == "${matched}" ]]; then',
        "            cands+=( ${opts[@]} )",
        "        fi",
        "    fi",
        '    COMPREPLY=( $(compgen -W "${cands[*]}" -- "${cur}" || true) )',
        "    return 0",
        "}",
        "",
        "complete -F _llm-router llm-router",
    ]
    return "\n".join(lines)


def _render_zsh(tree: Dict[str, Dict[str, Any]]) -> str:
    """Render a zsh completion function from *tree* (any nesting depth)."""
    paths = _flatten_paths(tree)
    lines: List[str] = [
        "#compdef llm-router",
        "# Tab completion for llm-router (zsh).",
        "# Install: source <(llm-router completion zsh)   # or append to ~/.zshrc",
        "_LR_PATHS=( {} )".format(" ".join(f"'{p}'" for p in paths)),
        "_LR_ROOT=( {} )".format(" ".join(f"'{n}'" for n in tree)),
        "_llm-router() {",
        "    local typed matched",
        "    local -a c=() cands=() opts=() subs=()",
        "    c=( ${words[@]:2:CURRENT-2} )",
        '    typed="${c[*]}"',
        '    typed="${typed%"${typed##*[! ]}"}"',
        '    if [[ -z "${typed}" ]]; then',
        "        cands=( ${_LR_ROOT[@]} )",
        "    else",
        "        for p in ${_LR_PATHS[@]}; do",
        '            if [[ "${typed}" == "${p}" || "${typed}" == "${p} "* ]]; then',
        '                matched="${p}"',
        "                break",
        "            fi",
        "        done",
    ]
    lines.extend(_path_case_lines(paths, "        "))
    lines += [
        "        cands=( ${opts[@]} ${subs[@]} )",
        "    fi",
        "    if (( ${#cands[@]} > 0 )); then",
        "        compadd -a cands",
        "    fi",
        "}",
        "",
        "if (( ${+functions[compdef]} )); then",
        "    compdef _llm-router llm-router",
        "fi",
    ]
    return "\n".join(lines)



def _begin_marker(shell: str) -> str:
    return "# >>> llm-router completion ({}) >>>".format(shell)


def _end_marker(shell: str) -> str:
    return "# <<< llm-router completion ({}) <<<".format(shell)


def _default_rc_file(shell: str) -> Path:
    """The default rc file for *shell* (``~/.bashrc`` / ``~/.zshrc``)."""
    name = ".bashrc" if shell == "bash" else ".zshrc"
    return Path.home() / name


def _install_block(content: str, shell: str, script: str) -> str:
    """
    Return *content* with the *script* installed in a marked block.

    An existing ``llm-router completion`` block for *shell* is replaced in
    place (idempotent re-install); otherwise the block is appended.
    """
    begin = _begin_marker(shell)
    end = _end_marker(shell)
    block_lines = [begin, script, end]
    lines = content.splitlines()
    start_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(lines):
        if start_idx is None and line.strip() == begin:
            start_idx = i
        elif start_idx is not None and line.strip() == end:
            end_idx = i
            break
    if start_idx is not None and end_idx is not None:
        return "\n".join(lines[:start_idx] + block_lines + lines[end_idx + 1:]) + "\n"
    if content:
        if not content.endswith("\n"):
            content += "\n"
        return content + "\n" + "\n".join(block_lines) + "\n"
    return "\n".join(block_lines) + "\n"


def _install(shell: str, script: str, target: Path) -> None:
    """Write *script* into *target* (created if missing), replacing any
    existing block for *shell*."""
    content = ""
    if target.exists():
        content = target.read_text(encoding="utf-8")
    target.write_text(_install_block(content, shell, script), encoding="utf-8")


class CompletionCommand(BaseCommand):
    """Print a shell tab-completion script for ``llm-router``."""

    NAME: ClassVar[str] = "completion"
    HELP: ClassVar[str] = "Print a shell tab-completion script (bash/zsh)"
    SUBPARSER_DEST: ClassVar[str] = "completion_command"

    BASH_NAME = "bash"
    ZSH_NAME = "zsh"
    BASH_HELP = "Print a bash completion script to stdout"
    ZSH_HELP = "Print a zsh completion script to stdout"

    # ---- Registration ---------------------------------------------------- #
    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the *bash* / *zsh* sub-commands."""
        bash_parser = subparsers.add_parser(cls.BASH_NAME, help=cls.BASH_HELP)
        zsh_parser = subparsers.add_parser(cls.ZSH_NAME, help=cls.ZSH_HELP)
        for parser, shell in ((bash_parser, "bash"), (zsh_parser, "zsh")):
            default_rc = "~/.bashrc" if shell == "bash" else "~/.zshrc"
            parser.add_argument(
                "--install",
                action="store_true",
                help=(
                    "Append the script to {} (created if missing) instead of "
                    "printing it; re-running replaces the existing block.".format(
                        default_rc
                    )
                ),
            )
            parser.add_argument(
                "--file",
                metavar="PATH",
                help="Target rc file for --install (default: {})".format(default_rc),
            )

    # ---- Dispatch -------------------------------------------------------- #
    @classmethod
    def _top_parser(cls) -> argparse.ArgumentParser:
        """Build the full top-level parser (lazy import avoids the cycle)."""
        from llm_router_cli.cli import COMMANDS

        parser = argparse.ArgumentParser(prog="llm-router")
        subparsers = parser.add_subparsers(dest="command")
        for command in COMMANDS:
            command.register(subparsers)
        return parser

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Print (or install) the completion script for the requested shell."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        if action not in (cls.BASH_NAME, cls.ZSH_NAME):
            cls.build_parser().print_help()
            return 0
        tree = _command_tree(cls._top_parser())
        script = _render_bash(tree) if action == cls.BASH_NAME else _render_zsh(tree)
        if not getattr(args, "install", False):
            print(script)
            return 0
        file_arg = getattr(args, "file", None)
        target = (
            Path(file_arg).expanduser() if file_arg else _default_rc_file(action)
        )
        try:
            _install(action, script, target)
        except OSError as exc:
            print(
                "Error: could not install {} completion to {}: {}".format(
                    action, target, exc
                ),
                file=sys.stderr,
            )
            return 1
        print("Installed {} completion to {}".format(action, target))
        print("Restart your shell or run: source {}".format(target))
        return 0
