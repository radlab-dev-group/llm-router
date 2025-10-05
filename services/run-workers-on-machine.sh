#!/bin/bash

# =============================================================================

function help_me() {
  echo "ERROR! Host is not given!"
  echo "Use the following syntax to run application:"
  echo ""
  echo "   ${0} <host.where.script.is.run>"
  echo ""
}

if [[ ${#} -lt 1 ]]
then
  help_me
  exit
fi
actual_host="${1}"
if [[ "${actual_host}" == "" ]]
then
  help_me
  exit
fi

# =============================================================================

source bash/constants.sh
source bash/colours.sh
source bash/general.sh

# Get and show configured hosts
show_get_configured_llama_hosts "${DIR_WITH_HOSTS_CONFIGS}"

# =============================================================================
# Run on host:
#   run_on_given_host <host> <gpu> <workers>
function run_on_given_host() {
  host="${1}"
  gpu="${2}"
  workers="${3}"
  ./run-worker-on-machine.sh \
    -h "${host}" \
    -g "${gpu}" \
    -w "${workers}"
}

# -----------------------------------------------------------------------------
# HOSTS TO RUN LLAMA SERVICE WITH VLLM
# -----------------------------------------------------------------------------
# General command format:
#   run_on_given_host <host> <gpu> <workers>
# -----------------------------------------------------------------------------
GPU_24GB_WORKERS_COUNT=5
GPU_48GB_WORKERS_COUNT=10

# -----------------------------------------------------------------------------
if [[ "${actual_host}" == "192.168.100.66" ]]
then
  run_on_given_host 192.168.100.66 0 "${GPU_24GB_WORKERS_COUNT}"
  run_on_given_host 192.168.100.66 1 "${GPU_24GB_WORKERS_COUNT}"
  run_on_given_host 192.168.100.66 2 "${GPU_24GB_WORKERS_COUNT}"
elif [[ "${actual_host}" == "192.168.100.69" ]]
then
  run_on_given_host 192.168.100.69 0 "${GPU_48GB_WORKERS_COUNT}"
elif [[ "${actual_host}" == "192.168.100.70" ]]
then
  run_on_given_host 192.168.100.70 0 "${GPU_24GB_WORKERS_COUNT}"
  run_on_given_host 192.168.100.70 1 "${GPU_24GB_WORKERS_COUNT}"
  run_on_given_host 192.168.100.70 2 "${GPU_24GB_WORKERS_COUNT}"
elif [[ "${actual_host}" == "192.168.100.71" ]]
then
  run_on_given_host 192.168.100.71 0 "${GPU_24GB_WORKERS_COUNT}"
  run_on_given_host 192.168.100.71 1 "${GPU_24GB_WORKERS_COUNT}"
elif [[ "${actual_host}" == "192.168.100.79" ]]
then
  run_on_given_host 192.168.100.79 0 "${GPU_24GB_WORKERS_COUNT}"
else
  no_config_for_host "${actual_host}"
fi
