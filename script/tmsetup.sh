#!/bin/bash
# Setup ansible for install

# User defined variables:
VENV_DIR=~/tm_venv


# Set Internal Variables
_THIS_SCRIPT=$0
_SCRIPT_DIR=$(dirname $_THIS_SCRIPT)
_START_DIR=$(pwd)
_BIN_PATH=${VENV_DIR}/bin
_EXTRA_VARS=""
_FORCE=false
_CONFIRM=false
_LOGFILE=~/tmsetup-$(date +%Y%m%d).log
_MIN_ANSIBLE_VERSION=10.7.0

_pline() { # Print line function
  printf '============================================================\n'
}
_usage() { # Print usage function
printf "%s [-d PATH][-o USER][-z TIMEZONE][-f|h|y] \n" "$_THIS_SCRIPT"
printf "Install Traffic Monitor software for Raspberry Pi\n\n"
printf "  %-20s%s\n" \
  "-d PATH" "Set PATH for traffic-monitor installation (default /opt/traffic-monitor)" \
  "-f" "FORCE to overwrite any existing configs with fresh copies from template" \
  "-g GROUP" "Set the GROUP owner of traffic-monitor files an processes (default tmadmin)" \
  "-h" "Show this usage output" \
  "-l PATH" "PATH to log file for output of installer (default $_LOGFILE)" \
  "-o USER" "Set the OWNER of traffic-monitor files and processes (default tmadmin)" \
  "-y" "Assume YES to all prompts including reboot" \
  "-z TIMEZONE" "Set TIMEZONE (default America/Los_Angeles)"
#  "-U" "UNINSTALL Traffic Monitor software" # Future addition
}

# Collect command-line options
while getopts ":fhyd:g:l:o:z:" opt
do
  case $opt in
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
      printf "Error: Invalid Option: -%s\n\n" "$OPTARG"
      _usage
      exit 1
      ;;
  esac
done
# Check if Log Path exists and create if not or exit
if ! [ -d "$(dirname $_LOGFILE)" ]
then
  mkdir -p $(dirname $_LOGFILE) || exit 1
fi
# Create log file or exit
touch $_LOGFILE || exit 1
# Log all further output to logfile
exec > >(tee -i $_LOGFILE)
exec 2>&1


# Confirming FORCE argument if not IGNORE CONFIRMATION
if [ "$_FORCE" = true ]
then
  if [ "$_CONFIRM" = false ]
  then
      printf 'Force argument passed.  Existing configurations will be overwritten with defaults.\n'
      read -p 'Are you sure you wish to continue? [yN] ' -n 1 -r CONT
      printf '\n'
      if [[ ! "$CONT" =~ ^[Yy]$ ]]
      then
        printf 'Installation cancelled.  Exitting...\n'
        exit 2
      fi
  fi
  _EXTRA_VARS="${_EXTRA_VARS} -e tmsetup_force_configs=true" 
fi

# Install Ansible in venv
_pline
printf "Installing and setting up Ansible\n"
_pline

# Check if python installed or install
if ! which python3 
then 
  printf 'Installing python3\n'
  sudo apt install python3
fi

# Check if pip installed in venv already
if ! [ -f ${_BIN_PATH}/pip3 ]
then
  printf "Installing python3 venv at %s\n" "${VENV_DIR}"
  python3 -m venv ${VENV_DIR}
fi

# Check Ansible version in venv if present
_ANSIBLE_VERSION=$(${_BIN_PATH}/pip3 show ansible | grep "^Version:" | tr -d '[:space:]' | cut -d: -f2)
if [ -f ${_BIN_PATH}/ansible-playbook ] && ( printf "%s\n%s\n" "${_MIN_ANSIBLE_VERSION}" "${_ANSIBLE_VERSION}" | sort --version-sort --check )
then
  printf "Ansible already installed and up to required version (%s).  Skipping...\n" "${_MIN_ANSIBLE_VERSION}"
else
  printf "Ansible not currently installed in venv at %s.  Installing...\n" "${VENV_DIR}"
  ${_BIN_PATH}/pip3 install "ansible>=${_MIN_ANSIBLE_VERSION}"
fi

# Initiate ansible playbook
_pline
printf "Running Ansible playbook to setup Traffic Monitor\n"
_pline
cd $_SCRIPT_DIR/ansible
${_BIN_PATH}/ansible-playbook -i localhost setup.yml ${_EXTRA_VARS}
_RETVAL=${PIPESTATUS[0]}

# Notify and exit on error
if [ $_RETVAL -ne 0 ]
then
  _pline
  printf "Something went wrong! Please review above logs.\n"
  _pline
  cd $_START_DIR
  exit 1
fi

_pline
printf "Setup completed succesfully!\n"
_pline

cd $_START_DIR

# Ask to reboot if not bypassed
if [ "$_CONFIRM" != true ]
then
  printf "Reboot is required to complete the installation.\n"
  read -p 'Do you wish to reboot now? [yN] ' -n 1 -r CONT
  printf "\n"
  if ! [[ $CONT =~ ^[Yy]$ ]]
  then
    printf "Reboot skipped. You will need to manually reboot this device to finalize tmsetup.\nExitting...\n"
    exit 0
  fi
else
  printf "Reboot confirmation skipped.  Rebooting system now.\n"
fi

# Reboot
sudo shutdown -r +1 "System is rebooting to finalize tmsetup.sh"

exit 0
