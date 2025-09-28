## Changelog

| Version | Changelog                                                                                                                                                         |
|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0.0.1   | Initialization, License, setup, interface for each endpoint and sample `ping` EP. Autoloader of builtin endpoints and for the future implementations.             |
| 0.0.2   | Add base models for api call (module `llm_proxy_rest.data_models` with `error.py` handling. Decorators to check required params and to measure the response time. |
| 0.0.3   | Proper `AutoLoading` for each found endpoint. Implementation of `ApiTypesDispatcher`, `ApiModelConfig`, `ModelHandler`                                            |