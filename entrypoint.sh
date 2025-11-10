#!/bin/bash

if [ "$1" = "SLEEP" ]; then
  echo "Debug mode"
  sleep infinity
else
  echo "Starting application..."
  exec ./run-rest-api.sh
fi
