"""
CLI command for the ``llm-router util`` subcommand group.

Ports the three ``llm-router-utils`` applications into the main CLI as light,
dependency‑free sub‑subcommands:

* ``llm-router util translate``
* ``llm-router util genai-classifier``
* ``llm-router util genai-data-augmentation``

Public API (exactly two methods, mirroring :class:`ConfigCommand`):

- :meth:`register_parser` – register the three sub‑subparsers under a parent.
- :meth:`run`             – standalone entry point; parse + dispatch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional


class UtilCommand:
    """
    Encapsulates the ``util`` CLI subcommand group and its three children.

    Public API (exactly two methods):
      - :meth:`register_parser` – register the *util* sub‑subcommands under a parent.
      - :meth:`run`            – standalone entry point; parse + dispatch.
    """

    NAME = "util"
    TRANSLATE = "translate"
    CLASSIFIER = "genai-classifier"
    AUGMENTATION = "genai-data-augmentation"

    TRANSLATE_HELP = "Translate texts in JSON/JSONL datasets via the LLMRouter"
    CLASSIFIER_HELP = "Classify translated datasets via the LLMRouter (JSONL only)"
    AUGMENTATION_HELP = "Augment a local JSONL dataset via the LLMRouter"

    DEFAULT_ROUTER_URL = "http://localhost:8080"

    # ------------------------------------------------------------------ #
    # Shared router-flag helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _add_router_host_args(p: argparse.ArgumentParser) -> None:
        """Add the ``--llm-router-host/token/timeout`` flags (translate)."""
        p.add_argument(
            "--llm-router-host",
            required=True,
            help="Base URL of the LLM router service (e.g., http://localhost:8080)",
        )
        p.add_argument(
            "--llm-router-token",
            required=False,
            default=None,
            help="Authentication token for the LLMRouter service.",
        )
        p.add_argument(
            "--llm-router-timeout",
            type=int,
            default=10,
            help="Per-request timeout in seconds for LLMRouter calls (default: 10).",
        )

    @staticmethod
    def _add_router_url_args(p: argparse.ArgumentParser) -> None:
        """Add the ``--llm-router-url/token/timeout`` flags (classifier/aug)."""
        p.add_argument(
            "--llm-router-url",
            default=UtilCommand.DEFAULT_ROUTER_URL,
            help="Base URL of the LLMRouter service (default: http://localhost:8080).",
        )
        p.add_argument(
            "--llm-router-token",
            required=False,
            default=None,
            help="Authentication token for the LLMRouter service.",
        )
        p.add_argument(
            "--llm-router-timeout",
            type=int,
            default=10,
            help="Per-request timeout in seconds for LLMRouter calls (default: 10).",
        )

    # ------------------------------------------------------------------ #
    # Per-subcommand argument definitions
    # ------------------------------------------------------------------ #
    @classmethod
    def _add_translate_args(cls, p: argparse.ArgumentParser) -> None:
        cls._add_router_host_args(p)
        p.add_argument(
            "--model",
            required=True,
            help="Model name to use for translation "
            "(e.g., speakleash/Bielik-11B-v2.3-Instruct)",
        )
        p.add_argument(
            "--dataset-path",
            action="append",
            required=True,
            help="Path to a dataset file (JSON or JSONL). Provide multiple times "
            "to process several files.",
        )
        p.add_argument(
            "--dataset-type",
            choices=["json", "jsonl"],
            default=None,
            help="Explicit type of dataset files (json or jsonl). "
            "If omitted, inferred from each file's extension.",
        )
        p.add_argument(
            "--accept-field",
            action="append",
            default=[],
            help="Field to retain/translate from each record. Can be supplied "
            "multiple times; if omitted all fields are kept.",
        )
        p.add_argument(
            "--num-workers",
            type=int,
            default=1,
            help="Number of worker threads for parallel translation (default: 1).",
        )
        p.add_argument(
            "--batch-size",
            type=int,
            default=8,
            help="How many texts to send in a single request (default: 8).",
        )
        p.add_argument(
            "-o",
            "--output",
            dest="output",
            default=None,
            help="Write all translated records to this single JSONL file. "
            "If omitted, each input <stem> produces <stem>.translated.jsonl "
            "next to it. The input files are never overwritten.",
        )

    @classmethod
    def _add_classifier_args(cls, p: argparse.ArgumentParser) -> None:
        cls._add_router_url_args(p)
        p.add_argument(
            "--dataset-dir",
            type=Path,
            required=True,
            help="Directory containing the local *.jsonl dataset files.",
        )
        p.add_argument(
            "--dataset-path",
            action="append",
            default=[],
            help="Explicit dataset file to process (in addition to the *.jsonl "
            "files in --dataset-dir). Can be supplied multiple times.",
        )
        p.add_argument(
            "--prompts-dir",
            type=Path,
            required=True,
            help="Directory with prompt (*.prompt) files.",
        )
        p.add_argument(
            "--output-dir",
            type=Path,
            required=True,
            help="Directory where the result .jsonl files are stored.",
        )
        p.add_argument(
            "--model-name",
            default="gpt-oss:120b",
            help="Model identifier passed to the router (default: gpt-oss:120b).",
        )
        p.add_argument(
            "--temperature",
            type=float,
            default=0.0,
            help="Sampling temperature for the model (default: 0.0).",
        )
        p.add_argument(
            "--batch-save-size",
            type=int,
            default=5,
            help="How many aggregated records are written to disk at once.",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Process data but do not write output files.",
        )
        p.add_argument(
            "--verbose",
            action="store_true",
            help="Enable DEBUG level logging.",
        )
        p.add_argument(
            "--num-workers",
            type=int,
            default=2,
            help="Number of parallel worker threads (default: 2).",
        )
        p.add_argument(
            "--n-sample",
            type=int,
            default=50,
            help="Number of samples per field (default: 50). "
            "Zero or negative processes all examples.",
        )
        p.add_argument(
            "--text-column-name",
            default="Tekst",
            help="Name of the column containing the text (default: 'Tekst').",
        )

    @classmethod
    def _add_augmentation_args(cls, p: argparse.ArgumentParser) -> None:
        cls._add_router_url_args(p)
        p.add_argument(
            "--dataset-path",
            type=Path,
            required=True,
            help="Path to the dataset file (local JSONL).",
        )
        p.add_argument(
            "--prompt-file",
            type=Path,
            required=True,
            help="Path to the prompt file.",
        )
        p.add_argument(
            "--labels",
            type=str,
            required=True,
            help="Comma-separated list of labels to augment.",
        )
        p.add_argument(
            "--n-samples",
            type=int,
            default=5,
            help="Number of random samples per class to augment (0 for all).",
        )
        p.add_argument(
            "--n-examples",
            type=int,
            default=3,
            help="Number of augmented examples the LLM should generate per text.",
        )
        p.add_argument(
            "--samples-as-examples",
            type=int,
            default=5,
            help="Number of random samples per class included in the prompt context.",
        )
        p.add_argument(
            "--model-name",
            default="gpt-oss:120b",
            help="Model identifier passed to the router (default: gpt-oss:120b).",
        )
        p.add_argument(
            "--temperature",
            type=float,
            default=0.7,
            help="Sampling temperature for the model (default: 0.7).",
        )
        p.add_argument(
            "--batch-save-size",
            type=int,
            default=5,
            help="How many records are written to disk at once.",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Process data but do not write output files.",
        )
        p.add_argument(
            "--output-dir",
            type=Path,
            default=None,
            help="Override directory where result files are stored.",
        )
        p.add_argument(
            "--verbose",
            action="store_true",
            help="Enable DEBUG level logging.",
        )
        p.add_argument(
            "--num-workers",
            type=int,
            default=2,
            help="Number of parallel worker threads (default: 2).",
        )
        p.add_argument(
            "--text-column-name",
            default="Tekst",
            help="Name of the column containing the text (default: 'Tekst').",
        )
        p.add_argument(
            "--label-column-name",
            default="label",
            help="Name of the column containing the label (default: 'label').",
        )

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    @classmethod
    def register_parser(cls, subparsers: argparse._SubParsersAction) -> None:
        """Register the three ``util`` sub‑subparsers under *subparsers*."""
        translate_p = subparsers.add_parser(cls.TRANSLATE, help=cls.TRANSLATE_HELP)
        cls._add_translate_args(translate_p)

        classifier_p = subparsers.add_parser(cls.CLASSIFIER, help=cls.CLASSIFIER_HELP)
        cls._add_classifier_args(classifier_p)

        augmentation_p = subparsers.add_parser(
            cls.AUGMENTATION, help=cls.AUGMENTATION_HELP
        )
        cls._add_augmentation_args(augmentation_p)

    # ------------------------------------------------------------------ #
    # Parser builder / entry point
    # ------------------------------------------------------------------ #
    @classmethod
    def build_parser(cls) -> argparse.ArgumentParser:
        """Build the standalone ``util`` parser (single source of the tree)."""
        parser = argparse.ArgumentParser(
            prog="llm-router util",
            description=(
                "Utility subcommands: translate, genai-classifier, "
                "genai-data-augmentation."
            ),
        )
        subparsers = parser.add_subparsers(dest="util_command")
        cls.register_parser(subparsers)  # type: ignore[arg-type]
        return parser

    @staticmethod
    def _exit_code(exc: SystemExit) -> int:
        """Normalize a ``SystemExit`` (from ``--help`` / argparse errors) to an int."""
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1

    @classmethod
    def run(cls, argv: Optional[List[str]] = None) -> int:
        """
        Standalone entry point: parse args and dispatch to a sub‑command.

        ``argv`` is expected to be the arguments *after* ``util`` (i.e. it may
        start with one of ``translate`` / ``genai-classifier`` /
        ``genai-data-augmentation``). A redundant leading ``util`` token is
        tolerated.
        """
        if argv is None:
            argv = sys.argv[1:]
        if argv and argv[0] == cls.NAME:
            argv = argv[1:]

        parser = cls.build_parser()
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:  # pragma: no cover - only on --help / errors
            return cls._exit_code(exc)

        action = getattr(args, "util_command", None)
        if action is None:
            parser.print_help()
            return 0

        handlers = {
            cls.TRANSLATE: cls._run_translate,
            cls.CLASSIFIER: cls._run_classifier,
            cls.AUGMENTATION: cls._run_augmentation,
        }
        handler = handlers.get(action)
        if handler is None:
            parser.print_help()
            return 1
        return handler(args)

    # ------------------------------------------------------------------ #
    # Sub-command handlers
    # ------------------------------------------------------------------ #
    @classmethod
    def _run_translate(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.translate import TranslateApp

        app = TranslateApp(args)
        try:
            app.run()
        except Exception as exc:
            print(f"Error running translate: {exc}", file=sys.stderr)
            return 1
        finally:
            app.close()
        return 0

    @classmethod
    def _run_classifier(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.genai_classifier import GenAIClassifierApp

        n_sample = args.n_sample if args.n_sample and args.n_sample > 0 else None
        app = GenAIClassifierApp(
            dataset_dir=args.dataset_dir,
            prompts_dir=args.prompts_dir,
            llm_router_url=args.llm_router_url,
            model_name=args.model_name,
            temperature=args.temperature,
            llm_router_token=args.llm_router_token,
            llm_router_timeout=args.llm_router_timeout,
            batch_save_size=args.batch_save_size,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            verbose=args.verbose,
            num_workers=args.num_workers,
            n_sample=n_sample,
            dataset_paths=args.dataset_path,
            text_column_name=args.text_column_name,
        )
        try:
            app.run()
        except Exception as exc:
            print(f"Error running genai-classifier: {exc}", file=sys.stderr)
            return 1
        return 0

    @classmethod
    def _run_augmentation(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.genai_data_augmentation import (
            GenAIDataAugmentationApp,
        )

        labels = [part for part in (args.labels or "").split(",") if part.strip()]
        app = GenAIDataAugmentationApp(
            dataset_path=args.dataset_path,
            prompt_path=args.prompt_file,
            labels=labels,
            llm_router_url=args.llm_router_url,
            model_name=args.model_name,
            llm_router_token=args.llm_router_token,
            llm_router_timeout=args.llm_router_timeout,
            temperature=args.temperature,
            n_samples=args.n_samples,
            n_examples=args.n_examples,
            samples_as_examples=args.samples_as_examples,
            batch_save_size=args.batch_save_size,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            verbose=args.verbose,
            num_workers=args.num_workers,
            text_column_name=args.text_column_name,
            label_column_name=args.label_column_name,
        )
        try:
            app.run()
        except Exception as exc:
            print(
                f"Error running genai-data-augmentation: {exc}", file=sys.stderr
            )
            return 1
        return 0
