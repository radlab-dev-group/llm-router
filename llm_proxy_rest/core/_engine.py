from typing import List, Type, Optional
from flask import Flask

from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.register.auto_loader import EndpointAutoLoader
from llm_proxy_rest.register.register import FlaskEndpointRegistrar
from llm_proxy_rest.base.constants import DEFAULT_API_PREFIX, REST_API_LOG_LEVEL


class FlaskEngine:
    def __init__(
        self,
        prompts_dir: str,
        models_config_path: str,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
    ) -> None:
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
        return flask_app

    def __auto_load_endpoints(self, base_class: Type[EndpointI]):
        """
        Discover and instantiate all concrete ``EndpointI`` subclasses
        found in the ``llm_proxy_rest.endpoints`` package.

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
            "llm_proxy_rest.endpoints"
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
