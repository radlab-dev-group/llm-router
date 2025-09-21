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
    _aut_loader = EndpointAutoLoader(
        base_class=EndpointI,
        prompts_dir=PROMPTS_DIR,
        logger_file_name=REST_API_LOG_FILE_NAME,
    )
    instances = _aut_loader.instantiate_without_args(
        classes=_aut_loader.discover_classes_in_package("llm_proxy_rest.endpoints")
    )
    if instances is None or not len(instances):
        raise RuntimeError("No endpoints found!")

    return instances


def __register_instances(application, instances: List[EndpointI]):
    with FlaskEndpointRegistrar(
        app=application, url_prefix=DEFAULT_API_PREFIX
    ) as registrar:
        registrar.register_endpoints(endpoints=instances)


def app():
    flask_app = Flask(__name__)
    try:
        __register_instances(
            application=flask_app, instances=__auto_load_endpoints()
        )
    except RuntimeError as e:
        raise RuntimeError(f"Failed to register endpoints: {e}")
    return flask_app


def main():
    app().run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
