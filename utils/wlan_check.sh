#!/bin/bash
# Script will check if wlan0 is operating nominally and if not, reset the device

# -q option runs this script without output unless there's an error

# use "journalctl -r -t wlan_check_log" to see output
QUIET="no"
while getopts "q" opt; do
	case $opt in
		q)
			QUIET="yes"
			;;
		\?)
			echo "Invalid option -$OPTARG"
			;;
	esac
done

ERROR=false
NETRESTARTCMD="sudo /usr/bin/systemctl restart NetworkManager.service"


_logallways() {
	logger -t wlan_check_log -- "$*"
}
_logoutput(){
	if [ "$QUIET" != "yes" ]
	then
  		_logallways "$*"
	fi
}

_logoutput "Starting wlan_check"

CONN_STATUS=$(nmcli networking connectivity)

if [[ $CONN_STATUS != "full" ]]
then
	#before network reset, log link status
	_logallways "***** Connectivity lost, dumping link status and restarting network interfaces *****"
	_IP=$(hostname -I) || true
	if [ "$_IP" ]; then
		_logallways "IP addresses: $_IP"
	fi
	_logallways "$(ip link show)"
	_logallways "$(nmcli device status)"
	_logallways "$(iwconfig wlan0)"
	
	_logallways "$($NETRESTARTCMD)"
	exit 1
else
	_logallways "No network connectivity issues detected"
	exit 0
fi
