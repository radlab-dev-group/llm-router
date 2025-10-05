CONFIGURED_HOSTS=()

function show_gpus_for_host() {
  hosts_conf_dir="${1}"

  for gpu in "${hosts_conf_dir}/llms"/*
  do
    if [[ -d "${gpu}" ]]
    then
      b_gpu="$(basename ${gpu})"
      echo -n -e "\t\t"
      echo -n -e "${COLOUR_BLUE}LLM-S"
      echo -n -e "${COLOUR_YELLOW} GPU:"
      echo -n -e "${COLOUR_RED} ${b_gpu}"
      echo -n -e "${COLOUR_NC}"
      echo
    fi
  done

  for gpu in "${hosts_conf_dir}/vllm"/*
  do
    if [[ -d "${gpu}" ]]
    then
      b_gpu="$(basename ${gpu})"
      echo -n -e "\t\t"
      echo -n -e "${COLOUR_CYAN}VLLM "
      echo -n -e "${COLOUR_YELLOW} GPU:"
      echo -n -e "${COLOUR_RED} ${b_gpu}"
      echo -n -e "${COLOUR_NC}"
      echo
    fi
  done
}

function show_get_configured_llama_hosts() {
  hosts_conf_dir=${1}

  echo
  echo -e "${COLOUR_CYAN}[*] All configured hosts:${COLOUR_NC}"
  for host in "${hosts_conf_dir}"/*
  do
    b_host="$(basename ${host})"
    CONFIGURED_HOSTS+=("${b_host}")
    echo -e -n "\t${COLOUR_YELLOW} [*] "
    echo -e -n "${COLOUR_GREEN}Found configuration for "
    echo -e -n "host ${COLOUR_BLUE}${b_host}${COLOUR_NC}"
    echo
    show_gpus_for_host "${host}"
  done
  echo
}


function show_run_info() {
  ip_addr="${1}"
  gpu="${2}"
  workers="${3}"

  echo -n -e "${COLOUR_CYAN}[*] "
  echo -n -e "${COLOUR_BLUE}Running llama service and vllm "
  echo -n -e "on ${COLOUR_RED}${ip_addr}"
  echo -n -e "${COLOUR_BLUE} and cuda device "
  echo -n -e "${COLOUR_YELLOW}${gpu}"
  echo -n -e "${COLOUR_BLUE} (workers="
  echo -n -e "${COLOUR_RED}${workers}"
  echo -n -e "${COLOUR_BLUE})"
  echo -n -e "${COLOUR_NC}"
  echo
}


function no_config_for_host() {
  host="${1}"

  echo -n -e "${COLOUR_RED}[ERROR] "
  echo -n -e "${COLOUR_BLUE}Cannot find configuration for host"
  echo -n -e "${COLOUR_YELLOW} ${host}\n"
  echo -n -e "${COLOUR_RED}[ERROR] "
  echo -n -e "${COLOUR_BLUE}Above are listed available hosts to choose."
  echo -n -e "${COLOUR_NC}"
  echo
}
