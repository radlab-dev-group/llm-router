from __future__ import annotations

import pkgutil
import importlib

from typing import Iterable, Dict, Any, Optional, Callable, Type, List, Set

from rdl_ml_utils.utils.logger import prepare_logger
from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.endpoints.endpoint_i import EndpointI


class EndpointAutoLoader:
    """
    Auto-discovery loader for EndpointI subclasses.

    This utility imports a target package (and its subpackages), discovers all
    subclasses of a given base class (EndpointI), and can instantiate them either:
    - without arguments (ideal when classes define url/method in __init__) or
    - from configuration (class path + args/kwargs).
    """

    def __init__(
        self,
        base_class: Type[EndpointI],
        prompts_dir: str,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = "DEBUG",
    ):
        """
        Parameters
        ----------
        base_class : Type[EndpointI]
            The common base class used to discover and type-check endpoints.
        prompts_dir : str
            The directory to look for prompts.
        logger_file_name: str, optional
            Logger file name, if not given, then will be used default from ml-utils.
        logger_level: str, optional (default="DEBUG")
            Logger level. Defaults to "DEBUG".
        """
        self.base_class = base_class
        self.prompts_dir = prompts_dir

        self._prompt_handler = PromptHandler(base_dir=prompts_dir)

        self._logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name,
            log_level=logger_level,
        )

    def discover_classes_in_package(
        self, package_name: str
    ) -> List[Type[EndpointI]]:
        """
        Import all modules in the provided package and return EndpointI subclasses.

        Notes
        -----
        - The package must be importable (present on PYTHONPATH).
        - Only subclasses whose __module__ starts with the package_name are returned.

        Parameters
        ----------
        package_name : str
            Fully qualified package name to search in
            (e.g., "llm_proxy_rest.endpoints").

        Returns
        -------
        List[Type[EndpointI]]
            List of discovered subclasses.
        """
        pkg = importlib.import_module(package_name)
        discovered: List[Type[EndpointI]] = []

        # Import submodules to ensure classes are registered in __subclasses__()
        for mod_info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            importlib.import_module(mod_info.name)

        # Collect all subclasses recursively
        def all_subclasses(cls_obj: Type[EndpointI]) -> Set[Type[EndpointI]]:
            subs: Set[Type[EndpointI]] = set()
            for sub in cls_obj.__subclasses__():
                subs.add(sub)
                subs.update(all_subclasses(sub))
            return subs

        for cls in all_subclasses(self.base_class):
            if cls.__module__.startswith(package_name):
                discovered.append(cls)

        return discovered

    def instantiate_without_args(
        self, classes: Iterable[Type[EndpointI]]
    ) -> List[EndpointI]:
        """
        Instantiate provided classes using a no-arg constructor.

        Any class that requires constructor arguments will be skipped with a warning.

        Parameters
        ----------
        classes : Iterable[Type[EndpointI]]
            Classes to be instantiated.

        Returns
        -------
        List[EndpointI]
            Successfully instantiated endpoints.
        """
        instances: List[EndpointI] = []
        for cls in classes:
            try:
                instances.append(cls())  # type: ignore[misc]
                self._logger.warning(f"Instantiating {cls.__name__}")
            except TypeError as e:
                self._logger.warning(
                    f"Cannot instantiate {cls.__name__} without arguments: {str(e)}"
                )
        return instances

    def instantiate_from_config(
        self,
        config: List[Dict[str, Any]],
        class_resolver: Optional[Callable[[str], Type[EndpointI]]] = None,
    ) -> List[EndpointI]:
        """
        Instantiate endpoints from a configuration list.

        Each entry must be a dict with:
        - "class": fully qualified class path (e.g., "pkg.endpoints.AddEndpoint")
        - "args": optional list of positional args
        - "kwargs": optional dict of keyword args

        Parameters
        ----------
        config : List[Dict[str, Any]]
            Parsed configuration entries.
        class_resolver : Callable[[str], Type[EndpointI]], optional
            Custom resolver mapping names to classes (e.g., a registry).
            If not provided, importlib is used based on class-value.

        Returns
        -------
        List[EndpointI]
            Instantiated endpoint objects.

        Raises
        ------
        TypeError
            If a resolved class is not a subclass of base_class.
        """
        instances: List[EndpointI] = []
        for item in config:
            class_path = item["class"]
            args = item.get("args", []) or []
            kwargs = item.get("kwargs", {}) or {}

            if class_resolver:
                cls = class_resolver(class_path)
            else:
                module_name, _, cls_name = class_path.rpartition(".")
                mod = importlib.import_module(module_name)
                cls = getattr(mod, cls_name)

            if not issubclass(cls, self.base_class):
                raise TypeError(
                    f"Class {cls} is not a subclass of {self.base_class}"
                )

            instances.append(cls(*args, **kwargs))
        return instances
