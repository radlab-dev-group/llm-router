"""
llm_router_api.core._engine
================================

This module provides the :class:`FlaskEngine` class, which builds and
configures a Flask application for the LLM‑proxy REST API.  The engine
automatically discovers concrete implementations of
:class:`~llm_router_api.endpoints.endpoint_i.EndpointI`, loads them with
default configuration (including prompt files and model settings), and
registers the resulting endpoint instances under the API prefix defined
by :data:`~llm_router_api.base.constants.DEFAULT_API_PREFIX`.

Typical usage
-------------
>>> engine = FlaskEngine(prompts_dir='resources/prompts',
...                     models_config_path='resources/configs/models-config.json')
>>> app = engine.prepare_flask_app()
>>> app.run()
"""

import traceback

from flask import Flask, Response
from typing import List, Type, Optional

from llm_router_api.endpoints.endpoint_i import EndpointI
from llm_router_api.register.auto_loader import EndpointAutoLoader
from llm_router_api.register.register import FlaskEndpointRegistrar
from llm_router_api.base.constants import (
    DEFAULT_API_PREFIX,
    REST_API_LOG_LEVEL,
    USE_PROMETHEUS,
)

if USE_PROMETHEUS:
    from llm_router_api.core.metrics import PrometheusMetrics


class FlaskEngine:
    """
    Engine responsible for creating a Flask application that automatically
    discovers, loads, and registers LLM‑proxy REST endpoints.

    Parameters
    ----------
    prompts_dir : str
        Path to the directory containing prompt files used by endpoints.
    models_config_path : str
        Path to the model configuration file (JSON/YAML) that describes
        the available LLM models.
    logger_file_name : Optional[str], optional
        File name for the engine's logger output. If ``None`` the logger
        uses the default configuration.
    logger_level : Optional[str], optional
        Logging level for the engine; defaults to
        :data:`~llm_router_api.base.constants.REST_API_LOG_LEVEL`.

    Notes
    -----
    The engine does not start the Flask server; it only prepares the
    application instance.  The caller is responsible for running the app
    (e.g., via ``app.run()`` or a WSGI server such as Gunicorn).

    If :data:`~llm_router_api.base.constants.USE_PROMETHEUS` is ``True``,
    a ``PrometheusMetrics`` instance is created during ``prepare_flask_app``
    and a ``/metrics`` endpoint is registered.  When the flag is ``False``,
    no Prometheus integration is performed.
    """

    def __init__(
        self,
        prompts_dir: str,
        models_config_path: str,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
    ) -> None:
        """
        Initialise the FlaskEngine.

        Parameters
        ----------
        prompts_dir : str
            Directory containing prompt files.
        models_config_path : str
            Path to the model configuration file.
        logger_file_name : Optional[str], optional
            Name of the log file; if omitted,
            the default logging configuration is used.
        logger_level : Optional[str], optional
            Logging level; defaults to
            :data:`~llm_router_api.base.constants.REST_API_LOG_LEVEL`.

        Notes
        -----
        The constructor stores the supplied configuration for
        later use by the auto‑loader and endpoint registrar.
        """
        self.prompts_dir = prompts_dir
        self.models_config_path = models_config_path

        self.logger_level = logger_level
        self.logger_file_name = logger_file_name

    def prepare_flask_app(
        self,
    ):
        """
        Create and configure the Flask application.

        Returns
        -------
        Flask
            A Flask instance with all discovered endpoints registered.

        Raises
        ------
        RuntimeError
            If endpoint registration fails for any reason.
        """
        flask_app = Flask(__name__)
        try:
            self.__register_instances(
                application=flask_app,
                instances=self.__auto_load_endpoints(base_class=EndpointI),
            )
        except RuntimeError as e:
            raise RuntimeError(f"Failed to register endpoints: {e}")

        self.__register_prometheus_if_needed(flask_app)

        return flask_app

    def __register_prometheus_if_needed(self, flask_app):
        """
        Register Prometheus metrics endpoint when ``USE_PROMETHEUS`` is enabled.

        Parameters
        ----------
        flask_app : Flask
            The Flask application instance to which the ``/metrics`` endpoint
            will be attached.

        The function silently returns if ``USE_PROMETHEUS`` is ``False``.
        """
        if not USE_PROMETHEUS:
            return

        try:
            _m = PrometheusMetrics(
                app=flask_app,
                logger_file_name=self.logger_file_name,
                logger_level=self.logger_level,
            )
            _m.register_metrics_ep()
        except Exception:
            raise RuntimeError(
                f"Failed to register endpoints: {traceback.format_exc()}"
            )

    def __auto_load_endpoints(self, base_class: Type[EndpointI]):
        """
        Discover and instantiate all concrete ``EndpointI`` subclasses
        found in the ``llm_router_api.endpoints`` package.

        Returns
        -------
        List[EndpointI]
            A list of ready‑to‑use endpoint instances.

        Raises
        ------
        RuntimeError
            If no endpoint classes are discovered or instantiated.
        """
        _auto_loader = EndpointAutoLoader(
            base_class=base_class,
            prompts_dir=self.prompts_dir,
            models_config_path=self.models_config_path,
            logger_file_name=self.logger_file_name,
            logger_level=self.logger_level,
        )

        classes = _auto_loader.discover_classes_in_package(
            "llm_router_api.endpoints"
        )

        instances = _auto_loader.instantiate_with_defaults(classes=classes)
        if instances is None or not len(instances):
            raise RuntimeError("No endpoints found!")

        return instances

    @staticmethod
    def __register_instances(application, instances: List[EndpointI]):
        """
        Register a collection of endpoint instances with a Flask application.

        Parameters
        ----------
        application : Flask
            The Flask app to which the endpoints will be attached.
        instances : List[EndpointI]
            A list of endpoint objects to register.

        The function uses ``FlaskEndpointRegistrar`` to bind
        each endpoint under the ``DEFAULT_API_PREFIX`` URL prefix.
        """
        with FlaskEndpointRegistrar(
            app=application, url_prefix=DEFAULT_API_PREFIX
        ) as registrar:
            registrar.register_endpoints(endpoints=instances)
