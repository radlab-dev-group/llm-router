#!/bin/bash

# =============================================================================
# Import libraries
source bash/constants.sh
source bash/colours.sh
source bash/general.sh
source bash/llms.sh

# =============================================================================

LLMS_SCRIPT_TO_RUN="run-fastapi.sh"
LLMS_CONFIG_TO_USE="gemma-3-12b-it-vllm.json"
VLLM_SCRIPT_TO_RUN="run-gemma-3-12b-it-vllm.sh"


# =============================================================================

function help()
{
   echo "Run llama-service workers on given machine and GPU device."
   echo
   echo "Syntax: run-workers-on-machine -i <ip.addr> -g <gpu-device>"
   echo "options:"
   echo "  -h   IP address of machine (from configs directory)"
   echo "  -g   GPU number to run"
   echo "  -w   number of llama-service workers"
   echo "  -H   Print this Help"
   echo
}

# =============================================================================

if [ ${#} -lt 6 ]
then
  help
  exit
fi

gpu=""
ip_addr=""
workers=""
# Check options
while getopts "H?h:g:w:" option;
do
   case "${option}" in
      h) ip_addr="${OPTARG}";
        ;;
      g) gpu="${OPTARG}";
        ;;
      w) workers="${OPTARG}";
        ;;
      H) help; exit;
        ;;
      ?) help; exit;
        ;;
   esac
done

if [[ "${gpu}" == "" ]] || [[ "${ip_addr}" == "" ]] || [[ "${workers}" == "" ]]
then
  help
  exit
fi

# =============================================================================

show_run_info "${ip_addr}" "${gpu}" "${workers}"

run_vllm_on_host \
  "${ip_addr}" \
  "${gpu}" \
  "${DIR_WITH_HOSTS_CONFIGS}" \
  "${VLLM_SCRIPT_TO_RUN}"
#
#run_llama_services_on_host \
#  "${ip_addr}" \
#  "${gpu}" \
#  "${workers}" \
#  "${DIR_WITH_HOSTS_CONFIGS}" \
#  "${LLMS_SCRIPT_TO_RUN}" \
#  "${LLMS_CONFIG_TO_USE}"

# =============================================================================
