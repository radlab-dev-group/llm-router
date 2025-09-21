from typing import List
from flask import Flask

from llm_proxy_rest.base.constants import (
    PROMPTS_DIR,
    REST_API_LOG_FILE_NAME,
    DEFAULT_API_PREFIX,
)
from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.register.auto_loader import EndpointAutoLoader
from llm_proxy_rest.register.register import FlaskEndpointRegistrar


def __auto_load_endpoints():
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
        base_class=EndpointI,
        prompts_dir=PROMPTS_DIR,
        logger_file_name=REST_API_LOG_FILE_NAME,
    )
    instances = _auto_loader.instantiate_without_args(
        classes=_auto_loader.discover_classes_in_package("llm_proxy_rest.endpoints")
    )
    if instances is None or not len(instances):
        raise RuntimeError("No endpoints found!")

    return instances


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


def _prepare_flask_app():
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
        __register_instances(
            application=flask_app, instances=__auto_load_endpoints()
        )
    except RuntimeError as e:
        raise RuntimeError(f"Failed to register endpoints: {e}")
    return flask_app


def run_flask_server(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    """
    Run the Flask development server for the LLM Proxy REST API.

    Parameters
    ----------
    host : str, optional
        Interface address to bind the server to. Defaults to ``"0.0.0.0"``.
    port : int, optional
        TCP port on which the server will listen to. Defaults to ``8080``.
    debug : bool, optional
        Enable Flask debug mode. Useful during development. Defaults to ``False``.

    The function creates the Flask application via `_prepare_flask_app`
    and starts it with the supplied configuration.
    """
    _prepare_flask_app().run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_flask_server(debug=True)
