#!/bin/bash
# Setup ansible for install

set -e

# NAMING: _lowercase for functions, UPPERCASE for user-editable variables,
# _UPPERCASE for internal-only variables, and plain lowercase for local variables inside functions

# TUNEABLE VARIABLES
TM_TMP_DIR=~/.tmsetup
VENV_DIR="${TM_TMP_DIR}/tm_venv"
REBOOT_TOUCH_FILE="${TM_TMP_DIR}/reboot-required"
TMP_INVENTORY_PATH="${TM_TMP_DIR}/inventory"

# INTERNAL VARIABLES
_THIS_SCRIPT=$0
_ARGS=("$@")
_SCRIPT_DIR=$(dirname "$_THIS_SCRIPT")
_START_DIR=$(pwd)
_ANSIBLE_CMD=""
_APT_UPGRADE=false
_BIN_PATH=${VENV_DIR}/bin
_EXIT_STATUS=0
_EXTRA_ARGS=""
_FORCE=false
_CONFIRM=false
_LOGFILE=~/tmsetup-$(date +%Y%m%d-%H%M).log
_MIN_ANSIBLE_VERSION=10.7.0
_REMOTE_HOSTS=''
declare _VALID_TAGS=("base" "full_upgrade" "wifi" "go2rtc" "detectors" "podman" "frigate" "node-red-tm" "plate-recognizer" "revproxy")
declare -a _VALID_CUSTOM_VARS=("plate_recognizer")
declare -a _CUSTOM_VARS=()

## FUNCTIONS
_pline() { # Print line function
  printf '============================================================\n'
}

_usage() { # Print usage function
printf "%s [-d PATH][-o USER][-z TIMEZONE][-f|h|y] \n" "${_THIS_SCRIPT}"
printf "Install Traffic Monitor software for Raspberry Pi\n\n"
printf "  %-20s%s\n" \
  "-a ARG" "Add a customer argument to the ansible-playbook run (do not include opening hyphen '-')" \
  "-d PATH" "Set PATH for traffic-monitor installation (default /opt/traffic-monitor)" \
  "-f" "FORCE to overwrite any existing configs with fresh copies from template" \
  "-g GROUP" "Set the GROUP owner of traffic-monitor files an processes (default tmadmin)" \
  "-h" "Show this usage output" \
  "-H HOSTNAME" "HOSTNAME for remote host execution.  Can be comma-seperated list of mulitiple" \
  "-l USERNAME" "LOGIN to for remote host execution" \
  "-L PATH" "PATH to LOGFILE file for output of installer (default ${_LOGFILE})" \
  "-k" "Prompt for password for remote host execution." \
  "-K" "Prompt for password for privilege escalation (sudo)." \
  "-o USER" "Set the OWNER of traffic-monitor files and processes (default tmadmin)" \
  "-t TAG" "TAG the ansible-playbook command to only run a subset of plays" \
  "-T" "Get a list of available tags and exit" \
  "-u" "Perform system UPGRADE (apt full-upgrade) as part of installation" \
  "-v" "Verbose ansible-playbook output. Call multiple times for increased verbosity" \
  "-y" "Assume YES to all prompts including reboot" \
  "-z TIMEZONE" "Set TIMEZONE (default America/Los_Angeles)" \
  "-C BOOL1[,BOOL2]" "Set custom boolean variables (comma‑separated) prefixed with tmsetup_bool_"
# "-R" "REMOVE Traffic Monitor software" # Future addition
}

_add_arg(){ # add an arg to ansible-playbook command
  local arg=$1
  _EXTRA_ARGS="${_EXTRA_ARGS} $arg"
  return 0
}

_add_var(){ # add a extra-var to ansible-playbook command
  local key=$1
  local val=$2
  _add_arg "--extra-vars $key=$val"
  return 0
}

_apt_upgrade(){ # perform full upgrade on local installs
  sudo apt update || return 1
  sudo apt full-upgrade || return 1
  return 0
}

_install_ansible_local() { # check and install python3-venv and setup venv
  local venvd=$1
  local script_dir=$2
  dpkg -s python3-venv >/dev/null 2>&1 || {
      sudo apt update && sudo apt install -y python3-venv
  }  
  if [[ ! -f "${venvd}/bin/activate" ]]; then
      echo "Virtual Environment does not exist and will be created at the following location:"
      echo "    ${venvd}"
      python3 -m venv "${venvd}" || return 1
  fi
  . "${venvd}/bin/activate" || return 1
  pip3 install -r "${script_dir}/requirements" || return 1
  return 0
}

_install_ansible_remote() { # check and install python3-venv and setup venv
  local venvd=$1
  local script_dir=$2
  if python3 -m venv ${venvd} ; then
    . "${venvd}/bin/activate" || return 1
    pip3 install -r "${script_dir}/requirements" || return 1
  else
    cat << EOF
ERROR: Unable to create python3 venv to install ansible. Possbly python3 or venv module are not installed.
  For Debian based systems:       sudo apt update && sudo apt install python3-venv
  For RHEL/Fedora/CentOS systems: sudo dnf install python3-libs
  For Arch based systems:         sudo pacman -Sy python-virutalenv
  for MacOS X:                    python3 -m pip install --user virtualenv
  For Windows:                    python3 -m pip install --user virtualenv
To install python you an follow the appropriate instructions for your operating system from:
  https://www.python.org/
EOF
    exit 1
  fi
  return 0
}

_log_check() { # Check if Log Path exists and create if not or exit
local logfil=$1
[[ -d "$(dirname "${logfil}")" ]] || mkdir -p "$(dirname "${logfil}")" || return 1

# Create log file or exit
touch "${logfil}" || ( printf "Unable to write to log file: %s\n" "${logfil}" && return 1 )
}

_confirm_cont() { # Request to confirm continuation
local cnftxt=$1
local contin=''
if [[ "${_CONFIRM}" == false ]]
then
  while ! [[ "${contin}" =~ ^[YyNn]$ ]] ;do
    read -p "${cnftxt}" -n 1 -r contin
    printf '\n'
    [[ "${contin}" =~ ^[Nn]$ ]] && return 2
  done
fi
return 0
}

_init_reboot_touchfile() { # Initialize the reboot touchfile 
  local tchfil=$1
  if [[ -n ${tchfil} ]] ;then
    _add_var tmsetup_reboot_touch_file "${tchfil}"
    printf '0' > ${tchfil} || return 1
  fi
  return 0
}

_set_tmp_ansible_inv() { # Setup ansible inventory for remote hosts
  local rhosts=$1
  local tmpinv=$2
  local -a hosts_array
  if [[ -n "${rhosts}" ]];then
    IFS=',' read -r -a hosts_array <<< ${rhosts}
    printf "[all]\n" > "${tmpinv}"
    printf "%s\n" ${hosts_array[@]} >> "${tmpinv}"
  fi
}

_print_result(){
  local exitst=$1
  _pline
  if [[ "${exitst}" -eq 0 ]]
  then
    printf "Setup completed SUCCESFULLY!\n"
  else
    printf "Setup completed with ERRORS!!\n"
  fi
  printf "Full output logged to: %s\n" "${_LOGFILE}"
  _pline
}

_run_ansible() { # Run _ANSIBLE_CMD; if sudo wanted a password Ansible didn't have, suggest -K
  local output status
  output=$(mktemp "${TM_TMP_DIR}/ansible-output.XXXXXX")
  # Copy the output to check for the sudo error; PIPESTATUS keeps the playbook's exit status
  ${_ANSIBLE_CMD} 2>&1 | tee -i "${output}"
  status=${PIPESTATUS[0]}
  if [[ ${status} -ne 0 ]] && grep -q -E 'sudo: a password is required|Missing sudo password' "${output}"; then
    printf "\n"
    _pline
    printf "Ansible stopped because sudo asked for a password.\n"
    printf "Run tmsetup.sh again with -K, and enter your sudo password when Ansible asks for it:\n\n"
    printf "    bash %s -K" "${_THIS_SCRIPT}"
    if [[ ${#_ARGS[@]} -gt 0 ]]; then
      printf " %q" "${_ARGS[@]}"
    fi
    printf "\n"
    _pline
  fi
  rm -f "${output}"
  return "${status}"
}

_tmsetup_local(){ # Installation on localhost only
  printf "This will install the traffic monitor software on this device: %s\n" "$(hostname)"
  _confirm_cont "Are you sure you wish to continue? [y|N] " || exit 2
  [[ -n "${TM_TMP_DIR}" ]] && _add_var tmsetup_tmp_dir "${TM_TMP_DIR}"
  _install_ansible_local "${VENV_DIR}" "${_SCRIPT_DIR}"
  _init_reboot_touchfile "${REBOOT_TOUCH_FILE}" || return 1
  . "${VENV_DIR}/bin/activate"
  cd "${_SCRIPT_DIR}/ansible"
  [[ "${_APT_UPGRADE}" == "true" ]] && ( _apt_upgrade || return 1 )
  printf "\n\n"
  _pline
  printf "Running Ansible playbook to setup Traffic Monitor\n"
  _pline
  _ANSIBLE_CMD="ansible-playbook -i localhost setup.yml ${_EXTRA_ARGS}"
  printf "\n\n%s\n\n" "${_ANSIBLE_CMD}"
  _run_ansible
  _EXIT_STATUS="$?"
  cd "${_START_DIR}"
  printf "\n\n"
  _print_result "${_EXIT_STATUS}"
  if [[ "$(<"${REBOOT_TOUCH_FILE}")" -ne 0 ]] ;then
    _pline
    printf "Reboot is required to complete the installation.\n"
    if _confirm_cont "Would you like to reboot now? [y|N] " ;then
      printf "Rebooting system now.\n"
      sudo shutdown -r +1 "System is rebooting to finalize tmsetup.sh"
      printf "\n"
    else
      printf "Reboot skipped. You will need to manually reboot this device to finalize tmsetup.\nExitting...\n"
    fi
  fi
  return ${_EXIT_STATUS}
}

_tmsetup_remote(){ # Installation on Remote hosts
  local rhosts=$1
  printf "This will install the traffic monitor software on these devices:\n\t%s\n" "${rhosts}"
  _confirm_cont "Are you sure you wish to continue? [y|N] " || exit 2
  [[ -n "${TM_TMP_DIR}" ]] && _add_var tmsetup_tmp_dir "${TM_TMP_DIR}"
  _install_ansible_remote "${VENV_DIR}" "${_SCRIPT_DIR}"
  . "${VENV_DIR}/bin/activate"
  cd "${_SCRIPT_DIR}/ansible"
  _set_tmp_ansible_inv "${rhosts}" "${TMP_INVENTORY_PATH}"
  [[ "${_APT_UPGRADE}" == "true" ]] && _add_var tmsetup_perform_apt_upgrade true
  printf "\n\n"
  _pline
  printf "Running Ansible playbook to setup Traffic Monitor on the following remote hosts:\n"
  printf "\t%s\n" "${rhosts}"
  _pline
  _ANSIBLE_CMD="ansible-playbook -i ${TMP_INVENTORY_PATH} setup_remote_hosts.yml ${_EXTRA_ARGS}"
  printf "\n\n%s\n\n" "${_ANSIBLE_CMD}"
  _run_ansible
  _EXIT_STATUS="$?"
  cd "${_START_DIR}"
  printf "\n\n"
  _print_result "${_EXIT_STATUS}"
  return ${_EXIT_STATUS}
}

### Start of MAIN

# Collect command-line options
while getopts ":fhkKTuvya:d:g:H:l:L:o:t:z:C:" opt;
do
  case ${opt} in
    a) # Add customer argumnet to ansible-playbook
      _add_arg "-${OPTARG}"
      ;;
    d) # Set PATH for install
      _add_var tmsetup_codedir "${OPTARG}"
      ;;
    f) # Force config overwrite
      _FORCE=true
      ;;
    g) # Set code GROUP
      _add_var tmsetup_codegroup "${OPTARG}"
      ;;
    H) # Set remote HOST execution
      if [[ -z "${_REMOTE_HOSTS}" ]];then
        _REMOTE_HOSTS="${OPTARG}"
      else
        _REMOTE_HOSTS="${_REMOTE_HOSTS},${OPTARG}"
      fi
      ;;
    l) # LOGIN for remote host execution
      _add_arg "-u ${OPTARG}"
      ;;
    L) # Log output to file
      _LOGFILE="${OPTARG}"
      ;;
    k) # Prompt for password for login for remote host execution
      _add_arg "-k"
      ;;
    K) # Prompt for password for privilege escalation (sudo)
      _add_arg "-K"
      ;;
    o) # Set Code OWNER
      _add_var tmsetup_codeowner "${OPTARG}"
      ;;
    t) # Set playbook TAG
      if [[ \ ${_VALID_TAGS[*]}\  =~ [[:space:]]${OPTARG}[[:space:]] ]] ;then
        _add_arg "--tags ${OPTARG}"
      else
        printf "Invalid Tag: %s\nExitting.\n\n" "${OPTARG}"
        exit 1
      fi
      ;;
    T) # Get TAG list
      printf "Valid Tags:\n"
      printf "  %s\n" ${_VALID_TAGS[@]}
      exit 2  
      ;;
    u) # Perform system upgrade as part of install
      _APT_UPGRADE=true
      ;;
    v) # Verbose output from ansible
      _add_arg "-v" 
      ;;
    y) # Ignore confirmation requests
      _CONFIRM=true
      ;;
    z) # Set Time Zone
      _add_var tmsetup_timezone "${OPTARG}"
      ;;
    h) # Show Usage
      _usage
      exit 2
      ;;
    C) # Custom boolean variables (comma‑separated)
      IFS=',' read -r -a _CUSTOM_VARS <<< "${OPTARG}"
      for v in "${_CUSTOM_VARS[@]}"; do
        # Trim any surrounding whitespace just to be safe
        v="${v#"${v%%[![:space:]]*}"}"   # ltrim
        v="${v%"${v##*[![:space:]]}"}"   # rtrim

        # Validate the variable name against the allowed list.
        if [[ ! " ${_VALID_CUSTOM_VARS[*]} " =~ " ${v} " ]]; then
          printf "Error: Custom variable '%s' is not permitted.\n" "$v"
          printf "Valid values are:\n  %s\n" "${_VALID_CUSTOM_VARS}"
          _usage
          exit 1
        fi

        # If it passes validation, add it as a true boolean.
        _add_var "tmsetup_bool_${v}" "true"
      done
      ;;
    :) #Catch Missing arguments
      printf "Error: Option -%s requires a PATH argument. \n" "${OPTARG}"
      _usage
      exit 1
      ;;
    ?) #Invalid option
      printf "Error: Invalid Option: -%s\n\n" "${OPTARG}"
      _usage
      exit 1
      ;;
  esac
done

mkdir -p "${TM_TMP_DIR}"
printf "This directory %s is just a tmp directory for traffic-monitor tmsetup.sh script.\n Everything in here can be safely deleted but future tmsetup.sh runs will take a bit longer.\n\nThank you,\n-The TM Team\n" "${TM_TMP_DIR}" > "${TM_TMP_DIR}/README.txt"

_log_check "${_LOGFILE}"
# Log all further output to logfile
exec > >(tee -i "${_LOGFILE}")
exec 2>&1

if [ "${_FORCE}" = true ]
then
  printf "\n"
  _pline
  printf "Force argument passed.  Existing configurations will be overwritten with defaults.\n"
  _pline
  if ! _confirm_cont "Are you sure you wish to continue? [y|N] " ;then
    printf "\nTMSetup cancelled.  Exitting.\n"
    exit 2
  fi
  _add_var tmsetup_force_configs "true" 
fi

if [[ -z "${_REMOTE_HOSTS}" ]] || [[ "${_REMOTE_HOSTS}" =~ ^,?localhost$ ]] ;then
  _tmsetup_local
else
  _tmsetup_remote "${_REMOTE_HOSTS}"
fi

exit ${_EXIT_STATUS}
