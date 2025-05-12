#!/bin/bash
# Setup ansible for install

# TUNEABLE VARIABLES
TM_TMP_DIR=~/.tmsetup
VENV_DIR="${TM_TMP_DIR}/tm_venv"
REBOOT_TOUCH_FILE="${TM_TMP_DIR}/reboot-required"
TMP_INVENTORY_PATH="${TM_TMP_DIR}/inventory"

# INTERNAL VARIABLES
_THIS_SCRIPT=$0
_SCRIPT_DIR=$(dirname "$_THIS_SCRIPT")
_START_DIR=$(pwd)
_APT_UPGRADE=false
_BIN_PATH=${VENV_DIR}/bin
_EXIT_STATUS=0
_EXTRA_ARGS=""
_FORCE=false
_CONFIRM=false
_LOGFILE=~/tmsetup-$(date +%Y%m%d-%H%M).log
_MIN_ANSIBLE_VERSION=10.7.0
_REMOTE_HOSTS=''
declare _VALID_TAGS=("base" "wifi" "docker" "frigate" "nodered" "go2rtc")

## FUNCTIONS
_pline() { # Print line function
  printf '============================================================\n'
}

_usage() { # Print usage function
printf "%s [-d PATH][-o USER][-z TIMEZONE][-f|h|y] \n" "${_THIS_SCRIPT}"
printf "Install Traffic Monitor software for Raspberry Pi\n\n"
printf "  %-20s%s\n" \
  "-d PATH" "Set PATH for traffic-monitor installation (default /opt/traffic-monitor)" \
  "-f" "FORCE to overwrite any existing configs with fresh copies from template" \
  "-g GROUP" "Set the GROUP owner of traffic-monitor files an processes (default tmadmin)" \
  "-h" "Show this usage output" \
  "-H HOSTNAME" "HOSTNAME for remote host execution.  Can be comma-seperated list of mulitiple" \
  "-l USERNAME" "LOGIN to for remote host execution" \
  "-L PATH" "PATH to LOGFILE file for output of installer (default ${_LOGFILE})" \
  "-k" "Prompt for password for remote host execution." \
  "-o USER" "Set the OWNER of traffic-monitor files and processes (default tmadmin)" \
  "-t TAG" "TAG the ansible-playbook command to only run a subset of plays" \
  "-T" "Get a list of available tags and exit" \
  "-u" "Perform system UPGRADE (apt full-upgrad) as part of installation" \
  "-v" "Verbose ansible-playbook output. Call multiple times for increased verbosity" \
  "-y" "Assume YES to all prompts including reboot" \
  "-z TIMEZONE" "Set TIMEZONE (default America/Los_Angeles)"
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

_install_ansible() { # check and install python3-venv and setup venv
local venv_dir=$1
dpkg -S python3-venv || ( sudo apt update && sudo apt install python3-venv )
while ! . "${venv_dir}/bin/activate" ;do 
  python3 -m venv "${venv_dir}"  || return 1
done
pip3 install -r "${_SCRIPT_DIR}/requirements" || return 1
return 0
}

_log_check() { # Check if Log Path exists and create if not or exit
local logfile=$1
[[ -d "$(dirname "${logfile}")" ]] || mkdir -p "$(dirname "${logfile}")" || return 1

# Create log file or exit
touch "${logfile}" || ( printf "Unable to write to log file: %s\n" "${logfile}" && return 1 )
}

_confirm_cont() { # Request to confirm continuation
local conf_text=$1
local cont=n
if [[ "${_CONFIRM}" == false ]]
then
  read -p "${conf_text}" -n 1 -r cont
  printf '\n'
  [[ "${cont}" =~ ^[Yy]$ ]] || return 1
fi
return 0
}

_init_reboot_touchfile() { # Initialize the reboot touchfile 
  local __tf=$1
  if [[ -n ${tf} ]] ;then
  _add_var tmsetup_reboot_touch_file "${tf}"
    touch ${tf} || return 1
    printf '0' > ${tf} || return 1
  fi
  return 0
}

_set_tmp_ansible_inv() { # Setup ansible inventory for remote hosts
  local _remote_hosts=$1
  local _tmp_inventory=$2
  if [[ -n "${_remote_hosts}" ]];then
    IFS=',' read -r -a _hosts_array <<< ${_remote_hosts}
    printf "[all]\n" > "${_tmp_inventory}"
    printf "%s\n" ${_hosts_array[@]} >> "${_tmp_inventory}"
  fi
}

### Start of MAIN

# Collect command-line options
while getopts ":fhkTuvyd:g:H:l:L:o:t:z:" opt
do
  case ${opt} in
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
      if [[ -n "${_REMOTE_HOSTS}" ]];then
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
    o) # Set Code OWNER
      _add_var tmsetup_codeowner "${OPTARG}"
      ;;
    t) # Set playbook TAG
      if [[ " ${_VALID_TAGS[*]} " =~ "[[:space:]]${OPTARG}[[:space:]]" ]] ;then
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
    y) # Ignore confirmation requests
      _CONFIRM=true
      ;;
    v) # Verbose output from ansible
      _add_arg "-v" 
      ;;
    z) # Set Time Zone
      _add_var tmsetup_timezone "${OPTARG}"
      ;;
    h) # Show Usage
      _usage
      exit 2
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

mkdir -p "${TM_TMP_DIR}" || exit
printf "This directory %s is just a tmp directory for traffic-monitor tmsetup.sh script.\n Everything in here can be safely deleted but future tmsetup.sh runs will take a bit longer.\n\nThank you,\n-The TM Team\n" "${TM_TMP_DIR}" > "${TM_TMP_DIR}/README.txt"

_log_check "${_LOGFILE}" || exit

# Log all further output to logfile
exec > >(tee -i "${_LOGFILE}")
exec 2>&1

if [[ -n "${_REMOTE_HOSTS}" ]];then
  _set_tmp_ansible_inv "${_REMOTE_HOSTS}" "${TMP_INVENTORY_PATH}"
fi
_init_reboot_touchfile "${REBOOT_TOUCH_FILE}" || exit $?

if [[ "${_APT_UPGRADE}" == "true" ]];then
  if [[ -z "${_REMOTE_HOSTS}" ]];then
    _apt_upgrade
  else
    _add_var tmsetup_perform_apt_upgrade true
  fi
fi

_install_ansible "${VENV_DIR}"
if [ "${_FORCE}" = true ]
then
  printf "Force argument passed.  Existing configurations will be overwritten with defaults.\n"
  if ! _confirm_cont "Are you sure you wish to continue? [yN] " ;then
    exit 2
  fi
  _add_var tmsetup_force_configs "true" 
fi

# Initiate ansible playbook
_pline
printf "Running Ansible playbook to setup Traffic Monitor\n"
_pline
cd "${_SCRIPT_DIR}/ansible" || exit
. "${VENV_DIR}/bin/activate" || exit

if [[ -z "${_REMOTE_HOSTS}" ]];then
  ANSIBLE_CMD="ansible-playbook -i localhost setup.yml ${_EXTRA_ARGS}"
else
  ANSIBLE_CMD="ansible-playbook -i "${TMP_INVENTORY_PATH}" setup_remote_hosts.yml ${_EXTRA_ARGS}"
fi

printf "%s\n" "${ANSIBLE_CMD}"
${ANSIBLE_CMD}

# Notify and exit on error
_EXIT_STATUS="${PIPESTATUS[0]}"

cd "${_START_DIR}" || exit

printf "\n\n\n"
_pline
if [[ "${_EXIT_STATUS}" -eq 0 ]]
then
  printf "Setup completed SUCCESFULLY!\n"
else
  printf "Setup completed with ERRORS!!\n"
fi
printf "Full output logged to: %s\n" "${_LOGFILE}"
_pline

# Ask to reboot if not bypassed
if [[ "$(<"${REBOOT_TOUCH_FILE}")" -ne 0 ]] && [[ -z "${_REMOTE_HOSTS}" ]] ;then
  _pline
  printf "Reboot is required to complete the installation.\n"
  if _confirm_cont "Would you like to reboot now? [yN] "
  then
    printf "Rebooting system now.\n"
    sudo shutdown -r +1 "System is rebooting to finalize tmsetup.sh"
    printf "\n"
  else
    printf "Reboot skipped. You will need to manually reboot this device to finalize tmsetup.\nExitting...\n"
  fi
fi

exit ${_EXIT_STATUS}
