"""
CLI command for the ``llm-router util`` subcommand group.

Ports the three ``llm-router-utils`` applications into the main CLI as light,
dependency‑free sub‑subcommands:

* ``llm-router util translate``
* ``llm-router util genai-classifier``
* ``llm-router util genai-data-augmentation``

The command is a :class:`~llm_router_cli.cli.commands.base.BaseCommand`: the
parser is built once (single source of truth) and dispatching happens on the
parsed namespace.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

from .base import BaseCommand


class UtilCommand(BaseCommand):
    """Encapsulates the ``util`` CLI subcommand group and its three children."""

    NAME: ClassVar[str] = "util"
    SUBPARSER_DEST: ClassVar[str] = "util_command"
    HELP: ClassVar[str] = (
        "Utility commands: translate, genai-classifier, genai-data-augmentation"
    )

    TRANSLATE = "translate"
    CLASSIFIER = "genai-classifier"
    AUGMENTATION = "genai-data-augmentation"

    TRANSLATE_HELP = "Translate texts in JSON/JSONL datasets via the LLMRouter"
    CLASSIFIER_HELP = "Classify translated datasets via the LLMRouter (JSONL only)"
    AUGMENTATION_HELP = "Augment a local JSONL dataset via the LLMRouter"

    DEFAULT_ROUTER_URL = "http://localhost:8080"
    DEFAULT_MODEL_NAME = "gpt-oss:120b"

    # ------------------------------------------------------------------ #
    # Shared argument helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _add_router_args(
        p: argparse.ArgumentParser,
        host_option: str,
        host_default: Optional[str],
        host_required: bool,
        host_help: str,
    ) -> None:
        """Add ``--llm-router-host/url`` + ``--llm-router-token/timeout`` flags."""
        p.add_argument(
            host_option,
            required=host_required,
            default=host_default,
            help=host_help,
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

    @classmethod
    def _add_shared_genai_args(
        cls, p: argparse.ArgumentParser, temperature_default: float
    ) -> None:
        """Add the flags shared by the classifier and augmentation commands."""
        p.add_argument(
            "--model-name",
            default=cls.DEFAULT_MODEL_NAME,
            help="Model identifier passed to the router "
            f"(default: {cls.DEFAULT_MODEL_NAME}).",
        )
        p.add_argument(
            "--temperature",
            type=float,
            default=temperature_default,
            help="Sampling temperature for the model.",
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
            "--verbose", action="store_true", help="Enable DEBUG level logging."
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

    # ------------------------------------------------------------------ #
    # Per-subcommand argument definitions
    # ------------------------------------------------------------------ #
    @classmethod
    def _add_translate_args(cls, p: argparse.ArgumentParser) -> None:
        cls._add_router_args(
            p,
            "--llm-router-host",
            None,
            True,
            "Base URL of the LLM router service (e.g., http://localhost:8080)",
        )
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
        cls._add_router_args(
            p,
            "--llm-router-url",
            cls.DEFAULT_ROUTER_URL,
            False,
            f"Base URL of the LLMRouter service (default: {cls.DEFAULT_ROUTER_URL}).",
        )
        cls._add_shared_genai_args(p, temperature_default=0.0)
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
            "--n-sample",
            type=int,
            default=50,
            help="Number of samples per field (default: 50). "
            "Zero or negative processes all examples.",
        )

    @classmethod
    def _add_augmentation_args(cls, p: argparse.ArgumentParser) -> None:
        cls._add_router_args(
            p,
            "--llm-router-url",
            cls.DEFAULT_ROUTER_URL,
            False,
            f"Base URL of the LLMRouter service (default: {cls.DEFAULT_ROUTER_URL}).",
        )
        cls._add_shared_genai_args(p, temperature_default=0.7)
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
            "--output-dir",
            type=Path,
            default=None,
            help="Override directory where result files are stored.",
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
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the three ``util`` leaf sub‑subcommands under *subparsers*."""
        translate_p = subparsers.add_parser(cls.TRANSLATE, help=cls.TRANSLATE_HELP)
        cls._add_translate_args(translate_p)

        classifier_p = subparsers.add_parser(
            cls.CLASSIFIER, help=cls.CLASSIFIER_HELP
        )
        cls._add_classifier_args(classifier_p)

        augmentation_p = subparsers.add_parser(
            cls.AUGMENTATION, help=cls.AUGMENTATION_HELP
        )
        cls._add_augmentation_args(augmentation_p)

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Route on the parsed namespace (no re-parsing of ``argv``)."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        handler = {
            cls.TRANSLATE: cls._run_translate,
            cls.CLASSIFIER: cls._run_classifier,
            cls.AUGMENTATION: cls._run_augmentation,
        }.get(action)
        if handler is None:
            cls.build_parser().print_help()
            return 0 if action is None else 1
        return handler(args)

    # ------------------------------------------------------------------ #
    # Sub-command handlers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _run_app(
        args: argparse.Namespace, app_factory: Callable[[Any], Any], label: str
    ) -> int:
        """Build, run and close an app, normalising errors to an exit code."""
        app = app_factory(args)
        try:
            app.run()
        except Exception as exc:
            print(f"Error running {label}: {exc}", file=sys.stderr)
            return 1
        finally:
            close = getattr(app, "close", None)
            if close is not None:
                close()
        return 0

    @classmethod
    def _run_translate(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.translate import TranslateApp

        return cls._run_app(args, TranslateApp, "translate")

    @classmethod
    def _run_classifier(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.genai_classifier import GenAIClassifierApp

        def build(a: argparse.Namespace) -> GenAIClassifierApp:
            n_sample = a.n_sample if a.n_sample and a.n_sample > 0 else None
            return GenAIClassifierApp(
                dataset_dir=a.dataset_dir,
                prompts_dir=a.prompts_dir,
                llm_router_url=a.llm_router_url,
                model_name=a.model_name,
                temperature=a.temperature,
                llm_router_token=a.llm_router_token,
                llm_router_timeout=a.llm_router_timeout,
                batch_save_size=a.batch_save_size,
                dry_run=a.dry_run,
                output_dir=a.output_dir,
                verbose=a.verbose,
                num_workers=a.num_workers,
                n_sample=n_sample,
                dataset_paths=a.dataset_path,
                text_column_name=a.text_column_name,
            )

        return cls._run_app(args, build, "genai-classifier")

    @classmethod
    def _run_augmentation(cls, args: argparse.Namespace) -> int:
        from llm_router_cli.util.genai_data_augmentation import (
            GenAIDataAugmentationApp,
        )

        def build(a: argparse.Namespace) -> GenAIDataAugmentationApp:
            labels = [part for part in (a.labels or "").split(",") if part.strip()]
            return GenAIDataAugmentationApp(
                dataset_path=a.dataset_path,
                prompt_path=a.prompt_file,
                labels=labels,
                llm_router_url=a.llm_router_url,
                model_name=a.model_name,
                llm_router_token=a.llm_router_token,
                llm_router_timeout=a.llm_router_timeout,
                temperature=a.temperature,
                n_samples=a.n_samples,
                n_examples=a.n_examples,
                samples_as_examples=a.samples_as_examples,
                batch_save_size=a.batch_save_size,
                dry_run=a.dry_run,
                output_dir=a.output_dir,
                verbose=a.verbose,
                num_workers=a.num_workers,
                text_column_name=a.text_column_name,
                label_column_name=a.label_column_name,
            )

        return cls._run_app(args, build, "genai-data-augmentation")
