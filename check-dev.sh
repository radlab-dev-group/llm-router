#!/bin/bash

black .

flake8 . --exclude="*/tests/*"

pylint ./llm_router_api --ignore=tests
pylint ./llm_router_cli --ignore=tests
pylint ./llm_router_lib --ignore=tests

mypy ./llm_router_api --exclude=tests
mypy ./llm_router_cli --exclude=tests
mypy ./llm_router_lib --exclude=tests

bandit -r .

pytest llm_router_api/tests
pytest llm_router_lib/tests
pytest llm_router_cli/tests
