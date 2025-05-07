#!/bin/bash
# Setup ansible for install

# User defined variables:
VENV_DIR=~/tm_venv


# Set Internal Variables
_THIS_SCRIPT=$0
_SCRIPT_DIR=$(dirname "$_THIS_SCRIPT")
_START_DIR=$(pwd)
_BIN_PATH=${VENV_DIR}/bin
_EXIT_STATUS=0
_EXTRA_VARS=""
_FORCE=false
_CONFIRM=false
_LOGFILE=~/tmsetup-$(date +%Y%m%d).log
_MIN_ANSIBLE_VERSION=10.7.0

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
  "-l PATH" "PATH to log file for output of installer (default ${_LOGFILE})" \
  "-o USER" "Set the OWNER of traffic-monitor files and processes (default tmadmin)" \
  "-v" "Verbose ansible-playbook output" \
  "-y" "Assume YES to all prompts including reboot" \
  "-z TIMEZONE" "Set TIMEZONE (default America/Los_Angeles)"
#  "-U" "UNINSTALL Traffic Monitor software" # Future addition
}

_install_ansible() { # Check if python installed or install
local venv_dir=$1
which python3 || sudo apt install python3 || return 1
. "${venv_dir}/bin/activate" > /dev/null || ( python3 -m venv "${venv_dir}"  && . "${venv_dir}/bin/activate" ) || return 1
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


# Collect command-line options
while getopts ":fhvyd:g:l:o:z:" opt
do
  case ${opt} in
    d) # Set PATH for install
      _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_codedir=${OPTARG}"
      ;;
    f) # Force config overwrite
      _FORCE=true
      ;;
    g) # Set code GROUP
      _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_codegroup=${OPTARG}"
      ;;
    l) # Log output to file
      _LOGFILE="${OPTARG}"
      ;;
    o) # Set Code OWNER
      _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_codeowner=${OPTARG}"
      ;;
    y) # Ignore confirmation requests
      _CONFIRM=true
      ;;
    v) # Verbose output from ansible
      _EXTRA_VARS="${_EXTRA_VARS} -v"
      ;;
    z) # Set Time Zone
      _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_timezone=${OPTARG}"
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

_log_check "${_LOGFILE}" || exit 1

# Log all further output to logfile
exec > >(tee -i "${_LOGFILE}")
exec 2>&1

_install_ansible "${VENV_DIR}"
if [ "${_FORCE}" = true ]
then
  printf "Force argument passed.  Existing configurations will be overwritten with defaults.\n"
  if ! _confirm_cont "Are you sure you wish to continue? [yN] " ;then
    exit 2
  fi
  _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_force_configs=true" 
fi

# Initiate ansible playbook
_pline
printf "Running Ansible playbook to setup Traffic Monitor\n"
_pline
cd "${_SCRIPT_DIR}/ansible" || exit 1
. "${VENV_DIR}/bin/activate" || exit 1
ansible-playbook -i localhost setup.yml ${_EXTRA_VARS}

# Notify and exit on error
[[ "${PIPESTATUS[0]}" -eq 0 ]] || _EXIT_STATUS=1

cd "${_START_DIR}" || exit "${_EXIT_STATUS}"

_pline
if [[ "${_EXIT_STATUS}" -eq 0 ]]
then
  printf "Setup completed succesfully!\n"
else
  printf "Setup completed with errors.  Review logs at: %s\n" "${_LOGFILE}"
  exit ${_EXIT_STATUS}
fi
_pline


# Ask to reboot if not bypassed
printf "\n\n\n"
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

exit 0
