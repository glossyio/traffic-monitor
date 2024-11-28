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
DOMAINADDR='duckduckgo.com'
GWADDR=$(ip route show | grep "^default" | cut -d\  -f3)
PUBNSADDRS=("8.8.8.8" "1.1.1.1" "9.9.9.9")
NETRESTARTCMD="systemctl restart NetworkManager"


_logallways() {
	logger -t wlan_check_log -- "$*"
}
_logoutput(){
	if [ "$QUIET" != "yes" ]
	then
  		_logallways "$*"
	fi
}
_logonerror(){
	CMD="$*"
	OUTPUT=$($CMD 2>&1)
	ES=$?
	if ((ES))
	then
		_logallways "------------- $CMD"
		_logallways "ERROR: $OUTPUT"
		ERROR=true
	fi
}
# try a command N times before declaring that it has failed
_repeat_command() {
	local CMD="$1"
  	local times="$2"
	for ((i = 0; i < times; i++)); do
		OUTPUT=$($CMD 2>&1)
		# Check if the command failed (non-zero exit status)
		if [ $? -ne 0 ]
		then
			_logallways "------------- $CMD"
			_logallways "ERROR on iteration $((i + 1)): $OUTPUT"
			ERROR=true
		else
			return 0
		fi
	done
}


_logoutput "==============================================================================="
_logoutput "Starting wlan_check"

_logoutput "ThingsBoard: $DOMAINADDR"
_logonerror "host $DOMAINADDR"
_repeat_command "ping -c1 $DOMAINADDR" 3

_logoutput "Gateway: $GWADDR"
_repeat_command "ping -c1 $GWADDR" 3

for ns in $(grep "^nameserver" /etc/resolv.conf|tr -s " " | cut -d\  -f2 | tr "\n" " ")
do
	_logoutput "Nameserver: $ns"
	_repeat_command "ping -c1 $ns" 3
done

for pubns in ${PUBNSADDRS[@]}
do
	_logoutput "Nameserver: $pubns"
	_repeat_command "ping -c1 $pubns" 3
done

if [[ $ERROR != "false" ]]
then
	#before network reset, log link status
	_logallways "***** restarting network"
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
	_logallways "No Network Issues Detected"
	exit 0
fi
