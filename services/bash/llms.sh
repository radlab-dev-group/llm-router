
function vllm_run_info() {
  host="${1}"
  gpu="${2}"
  configs_dir="${3}"
  vllm_script="${4}"

  echo -e -n "\t${COLOUR_GREEN}["
  echo -e -n "${COLOUR_RED}${host}"
  echo -e -n "${COLOUR_GREEN}] starting vllm "
  echo -e -n "\n\t  * run_script___: ${COLOUR_CYAN}${vllm_script}${COLOUR_GREEN}"
  echo -e -n "\n\t  * configs_dir__: ${COLOUR_CYAN}${configs_dir}${COLOUR_GREEN}"
  echo -e -n "${COLOUR_NC}"
}


function llama_service_run_info() {
  host="${1}"
  gpu="${2}"
  workers="${3}"
  configs_dir="${4}"
  llm_s_script="${5}"
  llm_s_config="${6}"

  echo -e -n "\t${COLOUR_GREEN}["
  echo -e -n "${COLOUR_RED}${host}"
  echo -e -n "${COLOUR_GREEN}] starting llama service "
  echo -e -n "\n\t  * run_script___: ${COLOUR_CYAN}${llm_s_script}${COLOUR_GREEN}"
  echo -e -n "\n\t  * configs_dir__: ${COLOUR_CYAN}${configs_dir}${COLOUR_GREEN}"
  echo -e -n "\n\t  * llm-s_config_: ${COLOUR_CYAN}${llm_s_config}${COLOUR_GREEN}"
  echo -e -n "\n\t  * workers_count: ${COLOUR_CYAN}${workers}${COLOUR_GREEN}"
  echo -e -n "${COLOUR_NC}"
}


function show_tmux_session_name() {
  session_name="${1}"
  add_tab="${2}"
  echo -e -n "${COLOUR_GREEN}"
  echo -e -n "\n\t${add_tab}  * tmux_session_: "
  echo -e -n "${COLOUR_CYAN}${session_name}${COLOUR_GREEN}"
  echo -e -n "${COLOUR_NC}"
}


function show_llm_s_port() {
  port_number="${1}"
  add_tab="${2}"
  echo -e -n "${COLOUR_GREEN}"
  echo -e -n "\n\t${add_tab}  * port_number__: "
  echo -e -n "${COLOUR_CYAN}${port_number}${COLOUR_GREEN}"
  echo -e -n "${COLOUR_NC}"
}


function run_vllm_on_host() {
  host="${1}"
  gpu="${2}"
  configs_dir="${3}"
  vllm_script="${4}"

  vllm_run_info \
    "${host}" \
    "${gpu}" \
    "${configs_dir}" \
    "${vllm_script}"

  run_vllm_on_host_now \
    "${host}" \
    "${gpu}" \
    "${configs_dir}" \
    "${vllm_script}"
}


function run_llama_services_on_host() {
  host="${1}"
  gpu="${2}"
  workers="${3}"
  configs_dir="${4}"
  llm_s_script="${5}"
  llm_s_config="${6}"

  llama_service_run_info \
    "${host}" \
    "${gpu}" \
    "${workers}" \
    "${configs_dir}" \
    "${llm_s_script}" \
    "${llm_s_config}"

  run_llama_services_on_host_now \
    "${host}" \
    "${gpu}" \
    "${workers}" \
    "${configs_dir}" \
    "${llm_s_script}" \
    "${llm_s_config}"
}


function run_vllm_on_host_now() {
  host="${1}"
  gpu="${2}"
  configs_dir="${3}"
  vllm_script="${4}"

  port_number="vllm-gpu-${gpu}"
  show_tmux_session_name "${port_number}"; echo ""

  vllm_config="${configs_dir}/${host}/vllm/${gpu}/${vllm_script}"
  tmux new-session -d -s "${port_number}"
  tmux send-keys -t "${port_number}" "bash ${vllm_config}" Enter
}


function run_single_llm_s_on_host_now() {
  host="${1}"
  gpu="${2}"
  workers="${3}"
  configs_dir="${4}"
  llm_s_script="${5}"
  llm_s_config="${6}"
  llm_s_port="${7}"

  session_name="llm-s-gpu-${gpu}-w${worker_num}-p${llm_s_port}"
  show_tmux_session_name "${session_name}" "\t"
  show_llm_s_port "${llm_s_port}" "\t"

  app_run="${configs_dir}/${host}/llms/${llm_s_script}"
  config_path="${configs_dir}/${host}/llms/${gpu}/${llm_s_config}"

  tmux_command="${app_run} ${gpu} ${port} ${config_path}"
  tmux new-session -d -s "${session_name}"
  tmux send-keys -t "${session_name}" "bash ${tmux_command}" Enter
}


function run_llama_services_on_host_now() {
  host="${1}"
  gpu="${2}"
  workers="${3}"
  configs_dir="${4}"
  llm_s_script="${5}"
  llm_s_config="${6}"

  ((workers=workers-1))
  for worker_num in $(seq 0 "${workers}");
  do
    port=8000
    gpu_p=gpu
    ((gpu_p=gpu_p*100))
    ((port=port+gpu_p))
    ((port=port+worker_num))
    run_single_llm_s_on_host_now \
      "${host}" \
      "${gpu}" \
      "${workers}" \
      "${configs_dir}" \
      "${llm_s_script}" \
      "${llm_s_config}" \
      "${port}"
  done
  echo ""
}
