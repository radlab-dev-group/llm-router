from flask import Flask

from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.register.auto_loader import EndpointAutoLoader
from llm_proxy_rest.register.register import FlaskEndpointRegistrar


def create_app():
    app = Flask(__name__)
    registrar = FlaskEndpointRegistrar(app=app, url_prefix="/api")

    loader = EndpointAutoLoader(base_class=EndpointI)
    classes = loader.discover_classes_in_package("llm_proxy_rest.endpoints")
    instances = loader.instantiate_without_args(classes)

    if instances is None or not len(instances):
        raise RuntimeError("No endpoints found!")

    registrar.register_endpoints(endpoints=instances)

    return app


def main():
    app = create_app()

    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
