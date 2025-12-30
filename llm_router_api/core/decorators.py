"""
llm_router_api.core.decorators
==============================

Utility decorators used by the REST‑endpoint classes.

The project’s endpoint hierarchy (`EndpointI` and `EndpointWithHttpRequestI`) relies
on two cross‑cutting concerns:

* **Parameter validation** – every endpoint can declare a list of required
  arguments (`EndpointI.REQUIRED_ARGS`).  Before the business logic runs we want
  to verify that those arguments are present and, if not, return a consistent
  error payload.

* **Execution‑time measurement** – for monitoring and debugging it is handy to
  add a ``response_time`` field (seconds) to the JSON response that an endpoint
  returns.

Both concerns are expressed as decorators that wrap the endpoint’s public
``call``‑style methods (normally ``run_ep`` or ``prepare_payload``).  The decorators
are defined as static methods of the ``EP`` namespace class so they can be used
with the ``@EP.require_params`` / ``@EP.response_time`` syntax without having to
instantiate anything.

Only the decorators are defined here; the actual validation logic lives in the
base endpoint class (`EndpointI._check_required_params`).  The decorators
simply forward to that logic and translate any raised :class:`ValueError` into
the library‑wide error format.
"""

import time
from typing import Callable, Any, Dict, Optional

from llm_router_api.core.errors import error_as_dict, ERROR_NO_REQUIRED_PARAMS


class EP:
    """
    Namespace container for endpoint‑related decorators.

    The class is never instantiated – the decorators are declared as
    ``@staticmethod``s so they can be applied directly to instance methods of
    endpoint classes.  Using a class (instead of module‑level functions) groups
    the decorators under a single, import‑friendly name:

    >>> from llm_router_api.core.decorators import EP
    >>> @EP.require_params
    ... def my_endpoint(self, params): ...

    The two decorators provided are:

    * :meth:`EP.require_params` – aborts the call early when required
      arguments are missing and returns a standard error payload.
    * :meth:`EP.response_time` – measures how long the wrapped method takes to
      execute and injects a ``response_time`` field into the returned mapping.
    """

    @staticmethod
    def require_params(
        func: Callable[[Any, Optional[Dict[str, Any]]], Any],
    ) -> Callable:
        """
        Validate required endpoint arguments before executing the wrapped method.

        The decorator expects the wrapped function to have the signature
        ``(self, params: Optional[dict])`` – exactly the shape used by the
        endpoint base classes.  Inside the wrapper the endpoint’s private
        ``_check_required_params`` method is called.  If that method raises a
        :class:`ValueError` (meaning one or more required arguments are
        missing) the decorator short‑circuits the call and returns an error
        payload that follows the library’s response convention:

        ``{"status": False, "body": {"error": "...", "error_msg": "..."} }``

        Parameters
        ----------
        func : Callable[[Any, Optional[Dict[str, Any]]], Any]
            The endpoint method to be wrapped
            (e.g. ``run_ep`` or ``prepare_payload``).

        Returns
        -------
        Callable
            A wrapper function that first performs the validation step and then
            forwards the call to *func* if validation succeeds.

        Notes
        -----
        * The wrapper treats a ``None`` ``params`` argument as an empty dictionary,
          because some endpoints do not require any input.
        * The error payload is built with
          :func:`llm_router_api.core.errors.error_as_dict`
          using the constant ``ERROR_NO_REQUIRED_PARAMS``.
        * The wrapper returns the result of *func* unchanged when validation passes.
        """

        def wrapper(self, params: Optional[Dict[str, Any]] = None):
            try:
                # ``params`` may be ``None`` – treat it as an empty dict
                self._check_required_params(params or {})
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

    @staticmethod
    def response_time(
        func: Callable[[Any, Optional[Dict[str, Any]]], Any],
    ) -> Callable:
        """
        Measure how long the wrapped endpoint method takes to execute.

        The decorator records a start time before invoking *func* and an end time
        afterward.  If the wrapped method returns a ``dict`` (the typical JSON
        payload for a successful endpoint), the decorator adds a new key
        ``response_time`` whose value is the elapsed time in **seconds** (float).

        Parameters
        ----------
        func : Callable[[Any, Optional[Dict[str, Any]]], Any]
            The endpoint method whose execution time should be measured.

        Returns
        -------
        Callable
            A wrapper that returns the original result of *func* with an added
            ``response_time`` field when the result is a mapping.

        Example
        -------
        >>> class MyEndpoint(EndpointI):
        ...     @EP.response_time
        ...     def run_ep(self, params):
        ...         # some work …
        ...         return {"status": True, "body": "ok"}
        ...
        >>> result = MyEndpoint().run_ep({})
        >>> "response_time" in result
        True
        """

        def wrapper(self, params: Optional[Dict[str, Any]] = None):
            start = time.time()
            result = func(self, params)
            end = time.time()
            if isinstance(result, dict):
                result = result.copy()
                result["response_time"] = end - start
            return result

        return wrapper
