#!/bin/bash

black .

flake8 . --exclude="*/tests/*"

pylint ./llm_router_api --ignore=tests
pylint ./llm_router_cli
pylint ./llm_router_lib

mypy ./llm_router_api
mypy ./llm_router_cli
mypy ./llm_router_lib

bandit -r .
