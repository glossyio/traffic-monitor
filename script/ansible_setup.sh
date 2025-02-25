#!/bin/bash
# Setup ansible for install

# User defined variables:
VENV_DIR=~/tm_venv


# Internal Variables
_THIS_SCRIPT=$0
_SCRIPT_DIR=$(dirname $_THIS_SCRIPT)
_START_DIR=$(pwd)
_BIN_PATH=${VENV_DIR}/bin

printf "===================================================\n"
printf "Installing and setting up Ansible\n"
printf "===================================================\n"

sudo apt install python3
python3 -m venv ${VENV_DIR}
${_BIN_PATH}/pip3 install ansible

printf "===================================================\n"
printf "Running Ansible playbook to setup Traffic Monitor\n"
printf "===================================================\n"
cd $_SCRIPT_DIR/ansible

${_BIN_PATH}/ansible-playbook setup.yml

if [ $? -ne 0 ]
then
  printf "===================================================\n"
  printf "Something went wrong! Please review above logs.\n"
  printf "===================================================\n"
  cd $_START_DIR
  exit 1
fi
printf "===================================================\n"
printf "Setup completed succesfully!\n"
printf "Please REBOOT the system to finalize the setup\n"
printf "===================================================\n"

cd $_START_DIR

exit 0
