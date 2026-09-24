"""
Shell tab-completion for ``llm-router`` (bash and zsh).

The script is generated from the *live* top-level parser, so completions
always match the registered commands, sub-commands and options — both the
long (``--instance``) and the short (``-i``) spellings::

    # bash — append to ~/.bashrc (or run once per shell):
    eval "$(llm-router completion bash)"

    # zsh — append to ~/.zshrc:
    source <(llm-router completion zsh)

Or install directly into the default rc file (``~/.bashrc`` / ``~/.zshrc``),
replacing any previous install on re-run::

    llm-router completion bash --install
    llm-router completion zsh --install --file ~/.config/zsh/completion.zsh

Options complete their *values* too, the way they were declared: the fixed
``choices=`` lists (``--color``, ``--store``, ``--lb-strategy`` …), the file
name options (``--log-file``, ``--output-dir``, ``config merge <files>``) and
the server instances (``-i``, ``server rm-instance <name>``).
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Tuple

from llm_router_cli.cli.commands.base import BaseCommand


def _option_strings(parser: argparse.ArgumentParser) -> List[str]:
    """
    All option strings declared on *parser* (no sub-commands).

    Long options are listed first and the short ones after them, so a menu
    reads ``--instance`` then ``-i``. The ``-h/--help`` action and the
    sub-command parser itself are skipped.
    """
    longs: List[str] = []
    shorts: List[str] = []
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        for opt in action.option_strings:
            if not opt.startswith("-") or opt in longs or opt in shorts:
                continue
            (longs if opt.startswith("--") else shorts).append(opt)
    return longs + shorts


#: Last segment of an option/argument name whose value is a filesystem path
#: (``--log-file``, ``--output-dir``, ``--models-config``), completed as a
#: file name.
_PATH_NAME_SUFFIXES: Tuple[str, ...] = ("file", "dir", "path", "config", "output")

#: Whole names of path arguments (``anonymizer run [input]``).
_PATH_ARG_NAMES: Tuple[str, ...] = ("input",)

#: Everything that marks an option/argument as carrying a path.
_PATH_MARKERS = frozenset(_PATH_NAME_SUFFIXES) | frozenset(_PATH_ARG_NAMES)

#: Command paths whose positional argument names a server instance.
_INSTANCE_POSITIONALS: Tuple[str, ...] = ("server rm-instance",)


def _path_segment(name: str) -> str:
    """Normalize ``--log-file`` / ``log_file`` to its last segment (``file``)."""
    if not name:
        return ""
    return name.replace("_", "-").rstrip("-").split("-")[-1].rstrip("s")


def _is_path_name(names: Iterable[str]) -> bool:
    """True when any of *names* marks a filesystem path (``--dataset-path`` …)."""
    return any(_path_segment(name) in _PATH_MARKERS for name in names)


#: argparse actions that never consume a value (``store_true`` and
#: ``store_false`` are ``store_const`` subclasses).
_FLAG_ACTIONS: Tuple[type, ...] = (
    argparse._StoreConstAction,
    argparse._CountAction,
    argparse._AppendConstAction,
    argparse._HelpAction,
    argparse._VersionAction,
)


def _takes_value(action: argparse.Action) -> bool:
    """True when the option consumes a value (``--port 8080``, not ``--force``)."""
    return not isinstance(action, _FLAG_ACTIONS) and action.nargs != 0


def _option_values(parser: argparse.ArgumentParser) -> Dict[str, List[str]]:
    """
    ``option string -> accepted values`` for every ``choices=`` option.

    Both spellings of an option are mapped, and options without a fixed
    value list are skipped (their completion is driven by
    :func:`_option_kind`).
    """
    values: Dict[str, List[str]] = {}
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        if not action.choices or not action.option_strings:
            continue
        accepted = [str(choice) for choice in action.choices]
        for opt in action.option_strings:
            values.setdefault(opt, accepted)
    return values


def _option_kind(parser: argparse.ArgumentParser) -> Dict[str, str]:
    """
    ``option string -> kind`` deciding how the option's value completes.

    ``flag`` takes no value, ``path`` completes file names, ``instance``
    completes the names of the local server instances, ``choice`` its
    ``choices=``, and ``value`` anything (nothing is proposed).
    """
    kinds: Dict[str, str] = {}
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        for opt in action.option_strings:
            if not _takes_value(action):
                kinds[opt] = "flag"
            elif action.choices:
                kinds[opt] = "choice"
            elif action.dest == "instance":
                kinds[opt] = "instance"
            elif _is_path_name([*action.option_strings, action.dest]):
                kinds[opt] = "path"
            else:
                kinds.setdefault(opt, "value")
    return kinds


def _metavar_names(action: argparse.Action) -> List[str]:
    """The metavar of *action* as a list (argparse allows one per positional)."""
    if action.metavar is None:
        return []
    if isinstance(action.metavar, str):
        return [action.metavar]
    return [str(name) for name in action.metavar]


def _positional_kind(parser: argparse.ArgumentParser, path: str) -> str:
    """``file`` / ``instance`` when *parser* takes such a positional."""
    for action in parser._actions:
        if action.option_strings or isinstance(action, argparse._SubParsersAction):
            continue
        if _is_path_name([action.dest, *_metavar_names(action)]):
            return "file"
        if path in _INSTANCE_POSITIONALS:
            return "instance"
    return ""


def _collect_by_path(tree: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Flatten *tree* to ``"cmd sub ..." -> node`` (every nesting depth)."""
    collected: Dict[str, Dict[str, Any]] = {}

    def rec(node: Dict[str, Any], prefix: Tuple[str, ...]) -> None:
        for name, info in node.items():
            path = " ".join(prefix + (name,))
            collected[path] = info
            rec(info["subs"], prefix + (name,))

    rec(tree, ())
    return collected


def _merge_option_values(tree: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """Merge the ``choices`` of every node into one option -> values map."""
    merged: Dict[str, List[str]] = {}
    for info in _collect_by_path(tree).values():
        for opt, accepted in info.get("values", {}).items():
            merged.setdefault(opt, list(accepted))
    return merged


def _merge_option_kinds(tree: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Merge the option kinds of every node into one option -> kind map."""
    merged: Dict[str, str] = {}
    for info in _collect_by_path(tree).values():
        for opt, kind in info.get("kinds", {}).items():
            merged.setdefault(opt, kind)
    return merged


def _paths_by_positional(tree: Dict[str, Dict[str, Any]], kind: str) -> List[str]:
    """Command paths whose positional argument is of *kind*."""
    return [
        path
        for path, info in _collect_by_path(tree).items()
        if info.get("positional_kind") == kind
    ]


def _group_by_kind(kinds: Dict[str, str]) -> Dict[str, List[str]]:
    """Invert *kinds* into ``kind -> option strings``, first-seen order."""
    grouped: Dict[str, List[str]] = {}
    for opt, kind in kinds.items():
        grouped.setdefault(kind, []).append(opt)
    return grouped


def _shell_case(options: List[str], result: str) -> str:
    """One ``case`` arm completing the *options* with *result*."""
    pattern = "|".join(f"'{opt}'" for opt in options)
    return f"        {pattern}) echo '{result}' ;;"


def _shell_array(name: str, values: Iterable[str]) -> str:
    """A shell array literal, e.g. ``_LR_ROOT=( 'auth' 'server' )``."""
    items = " ".join(f"'{value}'" for value in values)
    return f"{name}=( {items} )"


def _helper_lines(tree: Dict[str, Dict[str, Any]], instances: Path) -> List[str]:
    """
    Shell helpers shared by bash and zsh.

    They answer the three questions the completion function asks about the
    word before the cursor: what kind of value the option takes, which
    values are allowed, and which instance names exist on disk.
    """
    grouped = _group_by_kind(_merge_option_kinds(tree))
    lines: List[str] = [
        "_llm_router_in_list() {",
        '    local needle="$1" item',
        "    shift",
        '    for item in "$@"; do',
        '        [[ "${item}" == "${needle}" ]] && return 0',
        "    done",
        "    return 1",
        "}",
        "",
        "# How the value of an option completes (flag/value/path/instance/choice).",
        "_llm_router_opt_kind() {",
        '    case "$1" in',
    ]
    for kind in ("flag", "instance", "path", "choice"):
        if grouped.get(kind):
            lines.append(_shell_case(grouped[kind], kind))
    lines += [
        "        *) echo 'value' ;;",
        "    esac",
        "}",
        "",
        "# Accepted values of an option with a fixed list of choices.",
        "_llm_router_values() {",
        '    case "$1" in',
    ]
    for opt, accepted in _merge_option_values(tree).items():
        values = " ".join(f"'{value}'" for value in accepted)
        lines.append(f"        '{opt}') printf '%s\\n' {values} ;;")
    lines += [
        "    esac",
        "}",
        "",
        "# The server instances on disk ('default' plus the named ones).",
        "_llm_router_instances() {",
        # ``path`` is off-limits here: zsh ties it to ``PATH``.
        f'    local dir="{_shell_path(instances)}" entry',
        "    printf 'default\\n'",
        '    if [[ -d "${dir}" ]]; then',
        '        find "${dir}" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null |'
        " while IFS= read -r entry; do",
        "            printf '%s\\n' \"${entry##*/}\"",
        "        done",
        "    fi",
        "    return 0",
        "}",
        "",
    ]
    return lines


def _shell_path(path: Path) -> str:
    """Render *path* for a shell string, anchored at ``$HOME`` when possible."""
    home = Path.home()
    try:
        return f"${{HOME}}/{path.relative_to(home).as_posix()}"
    except ValueError:
        return path.expanduser().as_posix()


def _root_options(parser: argparse.ArgumentParser) -> List[str]:
    """Top-level options (``--version``), completed next to the commands."""
    return _option_strings(parser)


def _command_tree(
    parser: argparse.ArgumentParser,
    prefix: Tuple[str, ...] = (),
) -> Dict[str, Dict[str, Any]]:
    """
    Recursively extract the command tree from *parser*.

    Every node maps ``name -> {"options": [...], "subs": {name: node}}`` and
    also carries the accepted values, how each option's value completes and
    what kind of positional it takes, so any nesting depth (e.g. ``auth key
    generate``) is captured.
    """
    tree: Dict[str, Dict[str, Any]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            if name == "help" or sub is None:
                continue
            path = " ".join(prefix + (name,))
            tree[name] = {
                "options": _option_strings(sub),
                "values": _option_values(sub),
                "kinds": _option_kind(sub),
                "positional_kind": _positional_kind(sub, path),
                "subs": _command_tree(sub, prefix + (name,)),
            }
    return tree


def _flatten_paths(
    tree: Dict[str, Dict[str, Any]],
) -> Dict[str, Tuple[List[str], List[str], str]]:
    """
    Flatten *tree* into ``"cmd sub ..." -> (options, subcommands, arg kind)``.

    Ordered by path depth (parents before children) so the rendered case
    statements read top-down.
    """
    paths: Dict[str, Tuple[List[str], List[str], str]] = {}

    def rec(node: Dict[str, Any], prefix: Tuple[str, ...]) -> None:
        for name, info in node.items():
            p = prefix + (name,)
            paths[" ".join(p)] = (
                list(info["options"]),
                list(info["subs"]),
                info.get("positional_kind", ""),
            )
            rec(info["subs"], p)

    rec(tree, ())
    return dict(sorted(paths.items(), key=lambda kv: (-len(kv[0].split()), kv[0])))


def _path_case_lines(
    paths: Dict[str, Tuple[List[str], List[str], str]], indent: str
) -> List[str]:
    """Render the shared ``case "${matched}"`` clauses for one shell."""
    lines: List[str] = [
        indent + 'case "${matched}" in',
    ]
    for p, (opts, subs, _kind) in paths.items():
        lines.append(f'{indent}    "{p}")')
        if opts:
            lines.append(f"{indent}        " + _shell_array("opts", opts))
        if subs:
            lines.append(f"{indent}        " + _shell_array("subs", subs))
        lines.append(f"{indent}    ;;")
    lines.append(f"{indent}    *)")
    lines.append(f"{indent}        ;;")
    lines.append(f"{indent}    esac")
    return lines


def _render_bash(
    tree: Dict[str, Dict[str, Any]],
    root_options: List[str],
    instances: Path,
) -> str:
    """Render a bash completion function from *tree* (any nesting depth)."""
    paths = _flatten_paths(tree)
    lines: List[str] = [
        "# Tab completion for llm-router (bash).",
        '# Install: eval "$(llm-router completion bash)"   # or append to ~/.bashrc',
        _shell_array("_LR_PATHS", paths),
        _shell_array("_LR_ROOT", tree),
        _shell_array("_LR_ROOT_OPTS", root_options),
        _shell_array("_LR_FILE_ARGS", _paths_by_positional(tree, "file")),
        _shell_array("_LR_INSTANCE_ARGS", _paths_by_positional(tree, "instance")),
        "",
    ]
    lines.extend(_helper_lines(tree, instances))
    lines += [
        "_llm-router() {",
        '    local cur="${COMP_WORDS[COMP_CWORD]}"',
        '    local prev=""',
        '    (( COMP_CWORD > 0 )) && prev="${COMP_WORDS[COMP_CWORD - 1]}"',
        "    local i p typed matched kind",
        "    local -a c=() cands=() opts=() subs=() vals=()",
        "    i=1",
        "    while (( i < COMP_CWORD )); do",
        '        c+=("${COMP_WORDS[i]}")',
        "        i=$(( i + 1 ))",
        "    done",
        '    typed="${c[*]}"',
        '    typed="${typed%"${typed##*[! ]}"}"',
        '    matched=""',
        '    if [[ -n "${typed}" ]]; then',
        '        for p in "${_LR_PATHS[@]}"; do',
        '            if [[ "${typed}" == "${p}" || "${typed}" == "${p} "* ]]; then',
        '                matched="${p}"',
        "                break",
        "            fi",
        "        done",
        "    fi",
        '    if [[ -z "${matched}" ]]; then',
        "        subs=( ${_LR_ROOT[@]} )",
        "        opts=( ${_LR_ROOT_OPTS[@]} )",
        "    else",
    ]
    lines.extend(_path_case_lines(paths, "        "))
    lines += [
        "    fi",
        "    # An option before the cursor wants a value, not another option.",
        '    if [[ "${prev}" == -* && "${cur}" != -* ]]; then',
        '        kind="$(_llm_router_opt_kind "${prev}")"',
        '        case "${kind}" in',
        "            path)",
        '                COMPREPLY=( $(compgen -f -- "${cur}") )',
        "                _llm_router_filenames",
        "                return 0",
        "                ;;",
        "            instance)",
        "                vals=( $(_llm_router_instances) )",
        '                COMPREPLY=( $(compgen -W "${vals[*]}" -- "${cur}") )',
        "                return 0",
        "                ;;",
        "            choice)",
        '                vals=( $(_llm_router_values "${prev}") )',
        '                COMPREPLY=( $(compgen -W "${vals[*]}" -- "${cur}") )',
        "                return 0",
        "                ;;",
        "            flag)",
        "                ;;",
        "            *)",
        "                COMPREPLY=( )",
        "                return 0",
        "                ;;",
        "        esac",
        "    fi",
        "    cands=( ${subs[@]} ${opts[@]} )",
        '    if [[ "${cur}" != -* && -n "${matched}" ]]; then',
        '        if _llm_router_in_list "${matched}" "${_LR_FILE_ARGS[@]}"; then',
        '            COMPREPLY=( $(compgen -W "${cands[*]}" -- "${cur}")'
        ' $(compgen -f -- "${cur}") )',
        "            _llm_router_filenames",
        "            return 0",
        "        fi",
        '        if _llm_router_in_list "${matched}" "${_LR_INSTANCE_ARGS[@]}"; then',
        "            vals=( $(_llm_router_instances) )",
        '            COMPREPLY=( $(compgen -W "${cands[*]} ${vals[*]}" -- "${cur}") )',
        "            return 0",
        "        fi",
        "    fi",
        '    COMPREPLY=( $(compgen -W "${cands[*]}" -- "${cur}") )',
        "    return 0",
        "}",
        "",
        "# Let readline insert the trailing slash (and escape) of directories.",
        "_llm_router_filenames() {",
        "    if command -v compopt >/dev/null 2>&1; then",
        "        compopt -o filenames 2>/dev/null || true",
        "    fi",
        "}",
        "",
        "complete -F _llm-router llm-router",
    ]
    return "\n".join(lines)


def _render_zsh(
    tree: Dict[str, Dict[str, Any]],
    root_options: List[str],
    instances: Path,
) -> str:
    """Render a zsh completion function from *tree* (any nesting depth)."""
    paths = _flatten_paths(tree)
    lines: List[str] = [
        "#compdef llm-router",
        "# Tab completion for llm-router (zsh).",
        "# Install: source <(llm-router completion zsh)   # or append to ~/.zshrc",
        _shell_array("_LR_PATHS", paths),
        _shell_array("_LR_ROOT", tree),
        _shell_array("_LR_ROOT_OPTS", root_options),
        _shell_array("_LR_FILE_ARGS", _paths_by_positional(tree, "file")),
        _shell_array("_LR_INSTANCE_ARGS", _paths_by_positional(tree, "instance")),
        "autoload -Uz _files 2>/dev/null || true",
        "",
    ]
    lines.extend(_helper_lines(tree, instances))
    lines += [
        "_llm-router() {",
        '    local cur="${words[CURRENT]}"',
        '    local prev=""',
        '    (( CURRENT > 1 )) && prev="${words[CURRENT - 1]}"',
        "    local p typed matched kind",
        "    local -a c=() cands=() opts=() subs=() vals=()",
        "    # The words between the command and the one being completed.",
        '    c=( "${(@)words[2,CURRENT - 1]}" )',
        '    typed="${c[*]}"',
        '    typed="${typed%"${typed##*[! ]}"}"',
        '    matched=""',
        '    if [[ -n "${typed}" ]]; then',
        "        for p in ${_LR_PATHS[@]}; do",
        '            if [[ "${typed}" == "${p}" || "${typed}" == "${p} "* ]]; then',
        '                matched="${p}"',
        "                break",
        "            fi",
        "        done",
        "    fi",
        '    if [[ -z "${matched}" ]]; then',
        "        subs=( ${_LR_ROOT[@]} )",
        "        opts=( ${_LR_ROOT_OPTS[@]} )",
        "    else",
    ]
    lines.extend(_path_case_lines(paths, "        "))
    lines += [
        "    fi",
        "    # An option before the cursor wants a value, not another option.",
        '    if [[ "${prev}" == -* && "${cur}" != -* ]]; then',
        '        kind="$(_llm_router_opt_kind "${prev}")"',
        '        case "${kind}" in',
        "            path)",
        "                _llm_router_files",
        "                return 0",
        "                ;;",
        "            instance)",
        '                vals=( ${(f)"$(_llm_router_instances)"} )',
        "                compadd -a vals",
        "                return 0",
        "                ;;",
        "            choice)",
        '                vals=( ${(f)"$(_llm_router_values "${prev}")"} )',
        "                compadd -a vals",
        "                return 0",
        "                ;;",
        "            flag)",
        "                ;;",
        "            *)",
        "                return 0",
        "                ;;",
        "        esac",
        "    fi",
        "    cands=( ${subs[@]} ${opts[@]} )",
        '    if [[ "${cur}" != -* && -n "${matched}" ]]; then',
        '        if _llm_router_in_list "${matched}" "${_LR_FILE_ARGS[@]}"; then',
        "            compadd -a cands",
        "            _llm_router_files",
        "            return 0",
        "        fi",
        '        if _llm_router_in_list "${matched}" "${_LR_INSTANCE_ARGS[@]}"; then',
        '            vals=( ${cands[@]} ${(f)"$(_llm_router_instances)"} )',
        "            compadd -a vals",
        "            return 0",
        "        fi",
        "    fi",
        "    if (( ${#cands[@]} > 0 )); then",
        "        compadd -a cands",
        "    fi",
        "    return 0",
        "}",
        "",
        "# File names of the remaining arguments (compinit's own widget).",
        "_llm_router_files() {",
        "    if (( ${+functions[_files]} )); then",
        "        _files",
        "    fi",
        "}",
        "",
        "if (( ${+functions[compdef]} )); then",
        "    compdef _llm-router llm-router",
        "fi",
    ]
    return "\n".join(lines)


def _begin_marker(shell: str) -> str:
    return f"# >>> llm-router completion ({shell}) >>>"


def _end_marker(shell: str) -> str:
    return f"# <<< llm-router completion ({shell}) <<<"


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
        return (
            "\n".join(lines[:start_idx] + block_lines + lines[end_idx + 1 :]) + "\n"
        )
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
                    f"Append the script to {default_rc} (created if missing) "
                    "instead of printing it; re-running replaces the existing "
                    "block."
                ),
            )
            parser.add_argument(
                "--file",
                metavar="PATH",
                help=f"Target rc file for --install (default: {default_rc})",
            )

    # ---- Dispatch -------------------------------------------------------- #
    @classmethod
    def _top_parser(cls) -> argparse.ArgumentParser:
        """The real top-level parser, so completion cannot drift from the CLI."""
        from llm_router_cli.cli import build_parser

        return build_parser()

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Print (or install) the completion script for the requested shell."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        if action not in (cls.BASH_NAME, cls.ZSH_NAME):
            return cls.show_help(0)
        parser = cls._top_parser()
        tree = _command_tree(parser)
        # Instance names are completed from the instance state tree, so the
        # script points at the very directory ``server start`` writes to.
        from llm_router_cli.cli.commands.server import instances_dir

        context = (_root_options(parser), instances_dir())
        script = (
            _render_bash(tree, *context)
            if action == cls.BASH_NAME
            else _render_zsh(tree, *context)
        )
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
                f"Error: could not install {action} completion to {target}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"Installed {action} completion to {target}")
        print(f"Restart your shell or run: source {target}")
        return 0
