"""
Anonymisation command-line interface.

DEPRECATED: Use ``llm-router auth anonymizer --algorithm fast_masker`` instead
of the standalone ``llm-router-fast-masker`` entry point.  This module is kept
only for backward-compatibility and will be removed in a future release.
"""

import sys
import warnings

from llm_router_cli.cli.commands.anonymizer import main as _anonymizer_main


def main() -> int:
    """Deprecated entry point -- delegates to ``llm-router auth anonymizer``."""
    warnings.warn(
        "'llm-router-fast-masker' is deprecated. "
        "Use 'llm-router auth anonymizer --algorithm fast_masker' instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Forward all CLI arguments to the new anonymizer handler, defaulting to
    # fast_masker for the old interface which had no --algorithm flag.
    argv = ["--algorithm", "fast_masker"] + (
        sys.argv[1:] if len(sys.argv) > 1 else []
    )
    return _anonymizer_main(argv)


if __name__ == "__main__":
    sys.exit(main())
