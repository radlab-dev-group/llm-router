#!/bin/bash

black .

flake8 .

pylint ./llm_router_api
pylint ./llm_router_cli
pylint ./llm_router_lib

mypy .

bandit -r .
