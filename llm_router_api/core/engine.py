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

from flask import Flask, request, jsonify
from typing import List, Type, Optional

from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.core.monitor.services_monitor import LLMRouterServicesMonitor
from llm_router_api.endpoints.endpoint_i import EndpointI
from llm_router_api.register.auto_loader import EndpointAutoLoader
from llm_router_api.register.register import FlaskEndpointRegistrar
from llm_router_api.base.constants import (
    DEFAULT_API_PREFIX,
    REST_API_LOG_LEVEL,
    USE_PROMETHEUS,
    SERVER_BALANCE_STRATEGY,
    ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS,
    MAX_REQUEST_BODY_SIZE,
    LLM_ROUTER_AUTH_ENABLED,
    LLM_ROUTER_AUTH_KEY_STORE,
    LLM_ROUTER_AUTH_VAULT_ADDR,
    LLM_ROUTER_AUTH_VAULT_PATH,
    LLM_ROUTER_AUTH_VAULT_AUTH_METHOD,
    LLM_ROUTER_AUTH_VAULT_ROLE_ID,
    LLM_ROUTER_AUTH_VAULT_SECRET_ID,
    LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED,
    LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT,
    LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS,
    LLM_ROUTER_AUTH_KEY_CACHE_TTL,
    LLM_ROUTER_AUTH_KEY_CACHE_JITTER,
    LLM_ROUTER_AUTH_MEMORY_SEED_FILE,
    LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD,
    LLM_ROUTER_AUTH_AUDIT,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    LLM_ROUTER_AUTH_REDIS_HOST,
    LLM_ROUTER_AUTH_REDIS_PORT,
    LLM_ROUTER_AUTH_REDIS_DB,
    LLM_ROUTER_AUTH_REDIS_PASSWORD,
)
from llm_router_api.core.lb.provider_strategy_facade import ProviderStrategyFacade
from llm_router_api.core.auth.metrics import AuthMetrics

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

        self._provider_chooser = ProviderStrategyFacade(
            models_config_path=models_config_path,
            strategy_name=SERVER_BALANCE_STRATEGY,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
        )

        self._services_monitor = LLMRouterServicesMonitor(
            check_interval=ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            request_timeout=2.0,
        )

        self._services_monitor.start()

        self._auth_enabled = False
        self._auth_metrics: AuthMetrics | None = None

    # def __del__(self):
    #     if self._services_monitor:
    #         self._services_monitor.stop()

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
        flask_app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BODY_SIZE

        # -- AUTH ENABLED CHECK -------------------------------------------
        self._auth_enabled = LLM_ROUTER_AUTH_ENABLED

        if self._auth_enabled:
            self._setup_auth(flask_app)

        try:
            self.__register_instances(
                application=flask_app,
                instances=self.__auto_load_endpoints(base_class=EndpointI),
            )
        except RuntimeError as e:
            raise RuntimeError(f"Failed to register endpoints: {e}")

        self.__register_prometheus_if_needed(flask_app)

        # -- METRICS (after endpoints) --------------------------------------
        if USE_PROMETHEUS:
            self.__register_auth_metrics_if_needed(flask_app)

        return flask_app

    def _setup_auth(self, flask_app: Flask) -> None:
        """
        Set up the authentication system: key store, rate limiter, and middleware.

        This is called during ``prepare_flask_app()`` when ``LLM_ROUTER_AUTH_ENABLED``
        is ``"true"``.
        """
        from llm_router_api.base.constants import (
            LLM_ROUTER_AUTH_ENABLED,
            LLM_ROUTER_AUTH_KEY_STORE,
            LLM_ROUTER_AUTH_VAULT_ADDR,
            LLM_ROUTER_AUTH_VAULT_PATH,
            LLM_ROUTER_AUTH_VAULT_AUTH_METHOD,
            LLM_ROUTER_AUTH_VAULT_ROLE_ID,
            LLM_ROUTER_AUTH_VAULT_SECRET_ID,
            LLM_ROUTER_AUTH_KEY_CACHE_TTL,
            LLM_ROUTER_AUTH_KEY_CACHE_JITTER,
            LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD,
            LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED,
            LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT,
            LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS,
            LLM_ROUTER_AUTH_AUDIT,
            LLM_ROUTER_AUTH_KEY_PREFIX,
            LLM_ROUTER_AUTH_KEY_LENGTH,
            REDIS_HOST,
            REDIS_PORT,
            REDIS_DB,
            REDIS_PASSWORD,
            LLM_ROUTER_AUTH_REDIS_HOST,
            LLM_ROUTER_AUTH_REDIS_PORT,
            LLM_ROUTER_AUTH_REDIS_DB,
            LLM_ROUTER_AUTH_REDIS_PASSWORD,
        )
        from llm_router_api.core.auth import (
            create_key_store,
            RedisRateLimiter,
            PermissionEngine,
        )
        from llm_router_api.core.auth.middleware import install_auth_middleware
        from llm_router_api.core.auth.audit import AuthAuditorBridge
        from llm_router_api.core.auditor.auditor import AnyRequestAuditor
        import redis

        if not LLM_ROUTER_AUTH_ENABLED:
            return

        auth_logger = prepare_logger(
            "llm_router_api.auth",
            log_level=REST_API_LOG_LEVEL,
            use_default_config=True,
        )
        auth_logger.info("[AUTH] Authentication is ENABLED")

        # 1. Create the key store
        store_kwargs = {}
        if LLM_ROUTER_AUTH_KEY_STORE == "vault":
            store_kwargs = {
                "addr": LLM_ROUTER_AUTH_VAULT_ADDR,
                "mount_path": LLM_ROUTER_AUTH_VAULT_PATH,
                "auth_method": LLM_ROUTER_AUTH_VAULT_AUTH_METHOD,
                "role_id": LLM_ROUTER_AUTH_VAULT_ROLE_ID,
                "secret_id": LLM_ROUTER_AUTH_VAULT_SECRET_ID,
            }
        elif LLM_ROUTER_AUTH_KEY_STORE == "memory":
            store_kwargs = {
                "seed_file": LLM_ROUTER_AUTH_MEMORY_SEED_FILE,
            }
        elif LLM_ROUTER_AUTH_KEY_STORE == "redis":
            store_kwargs = {
                "redis_host": LLM_ROUTER_AUTH_REDIS_HOST,
                "redis_port": LLM_ROUTER_AUTH_REDIS_PORT,
                "redis_db": LLM_ROUTER_AUTH_REDIS_DB,
                "redis_password": LLM_ROUTER_AUTH_REDIS_PASSWORD,
            }

        store = create_key_store(LLM_ROUTER_AUTH_KEY_STORE, **store_kwargs)
        self._key_store = store

        # 2. Rate limiter
        rate_limiter = RedisRateLimiter(
            redis_client=store_kwargs.get("redis_client"),
            window=60,
        )
        self._rate_limiter = rate_limiter

        # 3. Permission engine
        perm_engine = PermissionEngine()
        self._perm_engine = perm_engine

        # 4. Auth config
        auth_config = {
            "public_endpoints": LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS,
            "rate_limit_enabled": LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED,
            "default_rate_limit": LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT,
            "rotation_grace_period": LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD,
            "key_prefix": LLM_ROUTER_AUTH_KEY_PREFIX,
            "key_length": LLM_ROUTER_AUTH_KEY_LENGTH,
            "audit_enabled": LLM_ROUTER_AUTH_AUDIT,
        }

        # 5. Install middleware
        install_auth_middleware(flask_app, store, auth_config)

        # 6. Audit bridge
        if LLM_ROUTER_AUTH_AUDIT:
            from llm_router_api.core.auditor.auditor import AnyRequestAuditor

            auditor = AnyRequestAuditor(
                logger=prepare_logger(
                    "llm_router_api.auth.audit",
                    log_level=REST_API_LOG_LEVEL,
                    use_default_config=True,
                )
            )
            self._auth_auditor_bridge = AuthAuditorBridge(auditor)

        self._auth_config = auth_config
        auth_logger = prepare_logger(
            "llm_router_api.auth",
            log_level=REST_API_LOG_LEVEL,
            use_default_config=True,
        )
        auth_logger.info("[AUTH] Auth system initialized successfully")

    def _register_auth_metrics(self):
        """Register auth Prometheus metrics."""
        from llm_router_api.core.auth.metrics import AuthMetrics

        if self._auth_metrics is not None:
            return  # Already registered

        self._auth_metrics = AuthMetrics()

        # Store auth metrics on flask_app.extensions for access
        self.flask_app.extensions["auth_metrics"] = self._auth_metrics

    def __register_prometheus_if_needed(self, flask_app: Flask) -> None:
        """
        Register Prometheus metrics endpoint when ``USE_PROMETHEUS`` is enabled.

        Parameters
        ----------
        flask_app : Flask
            The Flask application instance to which the ``/metrics`` endpoint
            will be attached.

        The function silently returns if ``USE_PROMETHEUS`` is ``False``.
        """
        # Store flask_app for later access
        self.flask_app = flask_app

        if not USE_PROMETHEUS:
            return

        try:
            _m = PrometheusMetrics(
                app=flask_app,
                logger_file_name=self.logger_file_name,
                logger_level=self.logger_level,
            )
            _m.register_metrics_ep()

            # Store on the Flask app so any helper can fetch it via
            # ``current_app.extensions['prometheus_metrics']``.
            flask_app.extensions = getattr(flask_app, "extensions", {})
            flask_app.extensions["prometheus_metrics"] = _m

            # Also keep a reference on the engine instance for direct access.
            self.prometheus_metrics = _m
        except Exception:
            raise RuntimeError(
                f"Failed to register endpoints: {traceback.format_exc()}"
            )

    def __register_auth_metrics_if_needed(self, flask_app: Flask) -> None:
        """
        Register auth Prometheus metrics alongside the standard HTTP metrics.

        This is called from ``prepare_flask_app()`` after the app is fully
        initialized.  It silently returns when Prometheus is disabled.
        """
        if not USE_PROMETHEUS or self._auth_metrics is not None:
            return

        from llm_router_api.core.auth.metrics import AuthMetrics

        self._auth_metrics = AuthMetrics()

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
            provider_chooser=self._provider_chooser,
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
