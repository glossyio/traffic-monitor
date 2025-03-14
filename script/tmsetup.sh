#!/bin/bash
# Setup ansible for install

# User defined variables:
VENV_DIR=~/tm_venv


# Internal Variables
_THIS_SCRIPT=$0
_SCRIPT_DIR=$(dirname $_THIS_SCRIPT)
_START_DIR=$(pwd)
_BIN_PATH=${VENV_DIR}/bin
_EXTRA_VARS=""
_FORCE=false
_CONFIRM=false
_LOGFILE=~/tmsetup-$(date +%Y%m%d).log

_pline() {
  printf '============================================================/n' | tee $_LOGFILE
}
_usage() {
printf "%s [-d PATH][-o USER][-z TIMEZONE][-f|h|y] \n" "$_THIS_SCRIPT"
printf "Install Traffic Monitor software for Raspberry Pi\n\n"
printf "  %-20s%s\n" \
  "-d PATH" "Set path for files (default /opt/traffic-monitor)" \
  "-f" "Pass to overwrite any existing configs with fresh copies from template" \
  "-h" "Show this usage output" \
  "-l PATH" "PATH to log file for output of installer (default $_LOGFILE)" \
  "-o USER" "Set the owner of traffic-monitor files and processes (default tmadmin)" \
  "-y" "Assume YES to all prompts including reboot" \
  "-z TIMEZONE" "Set timezone (default America/Los_Angeles)"
#  "--uninstall" "Uninstall Traffic Monitor software" \
}



while getopts ":fhyd:o:z:l:" opt
do
  case $opt in
    d) # Set PATH for install
      _EXTRA_VARS="${_EXTRA_VARS} tmsetup_codedir=${OPTARG}"
      ;;
    f) # Force config overwrite
      _FORCE=true
      ;;
    l) # Log output to file
      _LOGFILE="${OPTARG}"
      ;;
    o) # Set Code Owner
      _EXTRA_VARS="${_EXTRA_VARS} tmsetup_codeowner=${OPTARG}"
      ;;
    y) # Ignore confirmation requests
      _CONFIRM=true
      ;;
    z) # Set Time Zone
      _EXTRA_VARS="${_EXTRA_VARS} tmsetup_timezone=${OPTARG}"
      ;;
    h) # Show Usage
      _usage
      exit 2
      ;;
    \?) #Invalid option
      printf "Error: Invalid Option: %s\n\n" "$opt"
      _usage
      exit 1
      ;;
  esac
done
if [ "$_FORCE" = true ]
then
  if [ "$_CONFIRM" = false ]
  then
      printf 'Force argument passed.  Existinhg configurations will be overwritten with defaults.'
      read -p 'Are you sure you wish to continue? [yN] ' -n 1 -r CONT
      if [[ $CONT ~=^[Yy]$ ]]
      then
        _EXTRA_VARS="${_EXTRA_VARS} tmsetup_force_configs=true" 
      else
        printf 'Installation cancelled.  Exitting...\n'
        exit 2
      fi
  else
  fi
fi

pline
printf "Installing and setting up Ansible\n" | tee $_LOGFILE
pline

sudo apt install python3 | tee $_LOGFILE
python3 -m venv ${VENV_DIR} | tee $_LOGFILE
${_BIN_PATH}/pip3 install ansible | tee $_LOGFILE

pline
printf "Running Ansible playbook to setup Traffic Monitor\n" | tee $_LOGFILE
pline
cd $_SCRIPT_DIR/ansible | tee $_LOGFILE

${_BIN_PATH}/ansible-playbook setup.yml | tee $_LOGFILE

if [ $? -ne 0 ]
then
  pline
  printf "Something went wrong! Please review above logs.\n" | tee $_LOGFILE
  pline
  cd $_START_DIR | tee $_LOGFILE
  exit 1
fi
pline
printf "Setup completed succesfully!\n" | tee $_LOGFILE
pline
if [ "$_CONFIRM" != true ]
then
  printf "Reboot is required to complete the installation.\n"
  read -p 'Do you wish to reboot now? [yN] ' -n 1 -r CONT
  if [[ $CONT ~=^[Yy]$ ]]
  then
    sudo shutdown -r +1 "System is rebooting to finalize tmsetup.sh"
  else
    printf "Reboot skipped.  Exitting."
    exit 0
  fi
else
  printf "Reboot confirmation skipped.  Rebooting system now" | tee $_LOGFILE
  sudo shutdown -r +1 "System is rebooting to finalize tmsetup.sh" | tee $_LOGFILE
fi
  

cd $_START_DIR | tee $_LOGFILE

exit 0
