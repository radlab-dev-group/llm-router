"""
FlaskEndpointRegistrar

A tiny helper that wires `llm_proxy_rest.endpoints.endpoint_i.EndpointI`
objects into a Flask application (or Blueprint).
Only the registration logic is kept – validation of required / optional
arguments is left to the endpoint implementation itself.
"""

from __future__ import annotations

import logging

from flask import Flask, Blueprint, request, jsonify
from typing import Callable, Iterable, Any, Dict, Set, Tuple, Optional

from rdl_ml_utils.utils.logger import prepare_logger

from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.base.constants import DEFAULT_API_PREFIX


class FlaskEndpointRegistrar:
    """
    Register ``EndpointI`` instances as Flask routes.

    Parameters
    ----------
    app : Flask, optional
        Flask application that will receive the routes.
        Either *app* or *blueprint* must be supplied.
    blueprint : Blueprint, optional
        Blueprint to which the routes will be attached.
    url_prefix : str, optional
        Prefix prepended to every endpoint URL (e.g. ``"/api/v1"``).
    logger : logging.Logger, optional
        Logger used for diagnostic messages.
        If omitted, a module‑level logger is created.
    """

    def __init__(
        self,
        app: Optional[Flask] = None,
        blueprint: Optional[Blueprint] = None,
        url_prefix: str = DEFAULT_API_PREFIX,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if app is None and blueprint is None:
            raise ValueError("Either `app` or `blueprint` must be provided")

        self._app = app
        self._bp = blueprint

        self._prefix = ""
        if url_prefix and len(url_prefix):
            if not url_prefix.startswith("/"):
                url_prefix = "/" + url_prefix
            self._prefix = url_prefix

        self._logger = logger or prepare_logger(__name__, use_default_config=True)
        self._registered_rules: Set[Tuple[str, str]] = set()

    def register_endpoints(self, endpoints: Iterable[EndpointI]) -> None:
        """
        Register a collection of endpoints.

        Parameters
        ----------
        endpoints : Iterable[EndpointI]
            Any iterable producing concrete ``EndpointI`` objects.
        """
        for ep in endpoints:
            self.register_endpoint(ep)

    def register_endpoint(self, endpoint: EndpointI) -> None:
        """
        Register a single endpoint as a Flask view.

        The view simply extracts request parameters (query string for GET,
        JSON / form data for POST) and forwards them to ``endpoint.run_ep``.
        The result (or an empty dict) is returned as JSON with HTTP 200.

        Parameters
        ----------
        endpoint : EndpointI
            Concrete endpoint implementation.

        Raises
        ------
        RuntimeError
            If a route with the same URL and HTTP method has already been registered.
        """
        url = endpoint.name
        method = endpoint.method.upper()

        # Normalize the rule – ensure it starts with a slash and prepend prefix
        if not url.startswith("/"):
            url = "/" + url
        full_rule = f"{self._prefix}{url}"

        # Detect duplicates
        key = (full_rule, method)
        if key in self._registered_rules:
            raise RuntimeError(f"Duplicate route: {method} {full_rule}")
        self._registered_rules.add(key)

        # Build Flask view and register it
        view = self._make_view(endpoint)
        endpoint_name = f"{endpoint.__class__.__name__}:{method}:{full_rule}"

        if self._bp is not None:
            self._bp.add_url_rule(
                full_rule,
                endpoint=endpoint_name,
                view_func=view,
                methods=[method],
            )
        else:
            assert self._app is not None
            self._app.add_url_rule(
                full_rule,
                endpoint=endpoint_name,
                view_func=view,
                methods=[method],
            )

        self._logger.info(
            f"Registered endpoint {method} {full_rule} "
            f"({endpoint.__class__.__name__})",
        )

    def _make_view(self, endpoint: EndpointI) -> Callable[[], Any]:
        """
        Actual view function generator.

        It is deliberately tiny – no argument validation, just parameter
        extraction and a call to ``endpoint.run_ep``.
        """

        def handler():
            # 1 Extract parameters according to the HTTP method
            try:
                params = self._extract_params(endpoint.method)
            except Exception as exc:
                return jsonify({"error": "bad_request", "details": str(exc)}), 400

            # 2 Call the endpoint implementation
            try:
                # endpoint may return ``None``
                result = endpoint.run_ep(params or {})
                return jsonify(result or {}), 200
            except ValueError as ve:
                # user‑raised validation error
                return jsonify({"error": "bad_request", "details": str(ve)}), 400
            except Exception as exc:
                # any unexpected error -> 500
                self._logger.exception(
                    f"Unhandled exception in endpoint: "
                    f"{endpoint.__class__.__name__}",
                )
                return jsonify({"error": "internal_error", "details": str(exc)}), 500

        return handler

    @staticmethod
    def _extract_params(method: str) -> Dict[str, Any]:
        """
        Pull request data from Flask's ``request`` object.

        * **GET** – use ``request.args`` (query string).
        * **POST** – prefer JSON payload, fall back to ``request.form``.
        """
        method = method.upper()
        if method == "GET":
            return dict(request.args)
        if request.is_json:
            return request.get_json(silent=True) or {}
        return dict(request.form)

    def __enter__(self) -> "FlaskEndpointRegistrar":
        """
        Enter the runtime context and return the registrar instance.
        This makes ``FlaskEndpointRegistrar`` usable with the ``with`` statement.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Exit the runtime context.

        No special cleanup is required for the registrar, so we simply return
        ``False`` to propagate any exception that occurred inside the `with` block.
        """
        return False
