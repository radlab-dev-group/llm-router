"""
Shell tab-completion for ``llm-router`` (bash and zsh).

The script is generated from the *live* top-level parser, so completions
always match the registered commands, sub-commands and long options::

    # bash — append to ~/.bashrc (or run once per shell):
    eval "$(llm-router completion bash)"

    # zsh — append to ~/.zshrc:
    source <(llm-router completion zsh)
"""

from __future__ import annotations

import argparse

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
) -> Dict[str, Dict[str, List[str]]]:
    """
    Extract ``top command -> sub command -> long options`` from *parser*.

    Commands without sub-commands map to ``{"" : [opts]}`` so rendering
    stays uniform.
    """
    tree: Dict[str, Dict[str, List[str]]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            if name == "help" or sub is None:
                continue
            subs: Dict[str, List[str]] = {}
            for inner in sub._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    for inner_name, inner_parser in inner.choices.items():
                        if inner_name == "help" or inner_parser is None:
                            continue
                        subs[inner_name] = _long_options(inner_parser)
            if not subs:  # command without sub-commands: its own options
                subs = {"": _long_options(sub)}
            tree[name] = subs
    return tree


def _join_quoted_free(items: List[str]) -> str:
    """Space-join shell-safe words (no quoting needed for names/options)."""
    return " ".join(items)


def _render_bash(tree: Dict[str, Dict[str, List[str]]]) -> str:
    """Render a bash completion function from *tree*."""
    lines: List[str] = [
        "# Tab completion for llm-router (bash).",
        '# Install: eval "$(llm-router completion bash)"   # or append to ~/.bashrc',
        "_llm-router() {",
        '    local cur="${COMP_WORDS[COMP_CWORD]}"',
        '    local cmd="${COMP_WORDS[1]:-}"',
        '    local subs="{}"'.format(" ".join(tree)),
        "    if [[ ${COMP_CWORD} -eq 1 ]]; then",
        '        COMPREPLY=($(compgen -W "$subs" -- "$cur"))',
        "        return 0",
        "    fi",
        '    local name_subs="" opts=""',
        '    case "$cmd" in',
    ]
    for name, subs in tree.items():
        lines.append(f"        {name})")
        lines.append(f'            name_subs="{_join_quoted_free(subs)}"')
        lines.append("            if [[ ${COMP_CWORD} -eq 2 ]]; then")
        lines.append(
            '                COMPREPLY=($(compgen -W "$name_subs" -- "$cur"))'
        )
        lines.append("                return 0")
        lines.append("            fi")
        lines.append('            local sub="${COMP_WORDS[2]:-}"')
        lines.append('            case "$sub" in')
        for sub_name, opts in subs.items():
            if sub_name:
                lines.append(f"                {sub_name})")
                lines.append(f'                    opts="{_join_quoted_free(opts)}"')
                lines.append("                    ;;")
        lines.append("            esac")
        lines.append("            ;;")
    lines.append("        *)")
    lines.append("            ;;")
    lines.append("    esac")
    lines.append('    if [[ "$cur" == -* && -n "$opts" ]]; then')
    lines.append('        COMPREPLY=($(compgen -W "$opts" -- "$cur"))')
    lines.append("    fi")
    lines.append("    return 0")
    lines.append("}")
    lines.append("")
    lines.append("complete -F _llm-router llm-router")
    return "\n".join(lines)


def _render_zsh(tree: Dict[str, Dict[str, List[str]]]) -> str:
    """Render a zsh completion function from *tree*."""
    lines: List[str] = [
        "#compdef llm-router",
        "# Tab completion for llm-router (zsh).",
        "# Install: source <(llm-router completion zsh)   # or append to ~/.zshrc",
        "_llm-router() {",
        '    local prev="${words[CURRENT-1]:-}"',
        '    if [[ "$prev" == --* ]]; then',
        "        return 0",
        "    fi",
        '    local cmd="${words[2]:-}"',
        '    if [[ -z "$cmd" ]]; then',
        "        local subs=({})".format(" ".join(tree)),
        "        compadd -a subs",
        "        return 0",
        "    fi",
        '    case "$cmd" in',
    ]
    for name, subs in tree.items():
        lines.append(f"        {name})")
        sub_names = " ".join(f"'{n}'" for n in subs if n)
        lines.append(f"        local -a subs=({sub_names})")
        lines.append('        local sub="${words[3]:-}"')
        lines.append('        if [[ -z "$sub" || "$sub" == -* ]]; then')
        lines.append("            compadd -a subs")
        lines.append("            return 0")
        lines.append("        fi")
        lines.append('        case "$sub" in')
        for sub_name, opts in subs.items():
            if not sub_name or not opts:
                continue
            lines.append(f"            {sub_name})")
            lines.append(
                "            local -a opts=( {})".format(
                    " ".join(f"'{o}'" for o in opts)
                )
            )
            lines.append("            compadd -a opts")
            lines.append("            ;;")
        lines.append("        esac")
        lines.append("        ;;")
    lines.append("        *)")
    lines.append("            ;;")
    lines.append("    esac")
    lines.append("}")
    lines.append("")
    lines.append("# Register when the completion system is available")
    lines.append("if (( ${+functions[compdef]} )); then")
    lines.append("    compdef _llm-router llm-router")
    lines.append("fi")
    return "\n".join(lines)


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
        subparsers.add_parser(cls.BASH_NAME, help=cls.BASH_HELP)
        subparsers.add_parser(cls.ZSH_NAME, help=cls.ZSH_HELP)

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
        """Print the completion script for the requested shell."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        if action not in (cls.BASH_NAME, cls.ZSH_NAME):
            cls.build_parser().print_help()
            return 0
        tree = _command_tree(cls._top_parser())
        if action == cls.BASH_NAME:
            print(_render_bash(tree))
        else:
            print(_render_zsh(tree))
        return 0
