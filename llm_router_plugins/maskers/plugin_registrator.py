import logging
from typing import Optional


from llm_router_plugins.maskers.registry import (
    MAIN_MASKERS_REGISTRY,
    MASKERS_REGISTRY_SESSION,
)


class MaskerRegistry:
    """
    Central registry for masker plugins.

    This class provides static methods to register masker implementations,
    retrieve a registered masker by name, and list all currently registered
    maskers for the active session. It operates on two global registries:

    * ``MAIN_MASKERS_REGISTRY`` – a mapping from masker names to their
      factory callables defined by the plugin package.
    * ``MASKERS_REGISTRY_SESSION`` – a mutable mapping that holds instantiated
      masker objects for the duration of the current session.

    All methods are static because the registry is global and does not
    require a per ‑ instance state.
    """

    @staticmethod
    def register(name: str, logger: Optional[logging.Logger]):
        """
        Register a masker plugin for the current session.

        The function checks that the requested ``name`` exists in the global
        ``MAIN_MASKERS_REGISTRY``. If the masker has already been registered
        in ``MASKERS_REGISTRY_SESSION`` the call is a no‑op. Otherwise a new
        instance of the masker is created using the factory callable and stored
        in the session registry.

        Args:
            name: The identifier of the masker plugin to register.
            logger: Optional logger instance to be passed to the masker
                constructor. The exact type is defined by the plugin
                implementation.

        Raises:
            KeyError: If ``name`` is not present in ``MAIN_MASKERS_REGISTRY``.
        """
        if name not in MAIN_MASKERS_REGISTRY:
            raise KeyError(
                f"Masker '{name}' not found in registry: {MAIN_MASKERS_REGISTRY}"
            )

        if name in MASKERS_REGISTRY_SESSION:
            return

        _cls = MAIN_MASKERS_REGISTRY[name](logger=logger)
        MASKERS_REGISTRY_SESSION[name] = _cls
        logger.info(f"[masker] Registering masker '{name}' for plugin '{_cls}'")

    @staticmethod
    def get(name: str):
        """
        Retrieve a registered masker instance by its name.

        Args:
            name: Identifier of the masker plugin.

        Returns:
            The instantiated masker object associated with ``name``.

        Raises:
            KeyError: If the masker is not found in the session registry.
        """
        try:
            return MASKERS_REGISTRY_SESSION[name]
        except KeyError as exc:
            raise KeyError(
                f"Masker '{name}' not found in registry. Available plugins: "
                f"{str(MaskerRegistry.list_plugins())}"
            ) from exc

    @staticmethod
    def list_plugins() -> list[str]:
        """
        List all masker names that have been registered in the current session.

        Returns:
            A list of masker identifiers currently stored in
            ``MASKERS_REGISTRY_SESSION``.
        """
        return list(MASKERS_REGISTRY_SESSION.keys())
