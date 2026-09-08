#!/bin/bash

black .

flake8 . --exclude="*/tests/*"

pylint ./llm_router_api --ignore=tests
pylint ./llm_router_cli --ignore=tests
pylint ./llm_router_lib --ignore=tests

mypy ./llm_router_api
mypy ./llm_router_cli
mypy ./llm_router_lib

bandit -r .

pytest llm_router_api/tests --cov=llm_router_api -q
pytest llm_router_lib/tests --cov=llm_router_lib -q
pytest llm_router_cli/tests --cov=llm_router_cli -q
