from typing import Callable, Any, Dict, Optional

from llm_proxy_rest.core.errors import error_as_dict, ERROR_NO_REQUIRED_PARAMS


class EP:
    @staticmethod
    def require_params(
        func: Callable[[Any, Optional[Dict[str, Any]]], Any],
    ) -> Callable:
        """
        Decorator for endpoint ``call`` methods.

        It runs ``self.check_required_params`` before the wrapped method.
        If a ``ValueError`` is raised, the decorator returns a ``status: False``
        payload built with ``error_as_dict`` and ``return_response_not_ok``.
        """

        def wrapper(self, params: Optional[Dict[str, Any]] = None):
            try:
                # ``params`` may be ``None`` – treat it as an empty dict
                self.check_required_params(params or {})
            except ValueError as exc:
                # Build the error payload and return it directly
                return self.return_response_not_ok(
                    error_as_dict(
                        error=ERROR_NO_REQUIRED_PARAMS,
                        error_msg=str(exc),
                    )
                )
            # All required params are present – proceed with the original logic
            return func(self, params)

        return wrapper
