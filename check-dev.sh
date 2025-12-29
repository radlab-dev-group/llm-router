#!/bin/bash

black .

flake8 .

pylint ./*

mypy .

bandit -r .
