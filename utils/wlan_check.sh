#!/bin/bash
# Script will check if wlan0 is operating nominally and if not, reset the device

ERROR=false
LOGFILE=/var/log/wlan_check.log
DOMAINADDR='duckduckgo.com'
GWADDR=$(ip route show | grep "^default" | cut -d\  -f3)
PUBNSADDRS=("8.8.8.8" "1.1.1.1" "9.9.9.9")
NETRESTARTCMD="systemctl restart NetworkManager"

_logoutput(){
  echo "$(date +%D_%T): $*" >> $LOGFILE 2>&1
}
_logonerror(){
	CMD="$*"
	OUTPUT=$($CMD 2>&1)
	ES=$?
	if ((ES))
	then
		_logoutput "------------- $CMD"
		_logoutput "ERROR: $OUTPUT"
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
			_logoutput "------------- $CMD"
			_logoutput "ERROR on iteration $((i + 1)): $OUTPUT"
		else
			return 0
		fi
	done
	ERROR=true
}


_logoutput "==============================================================================="
_logoutput "Starting wlan_check"

_logoutput "ThingsBoard: $DOMAINADDR"
_logonerror "host $DOMAINADDR"
_repeat_command "ping -c1 $DOMAINADDR" 3

_logoutput "Gateway: $GWADDR"
_repeat_command "ping -c1 $GWADDR" 3

_IP=$(hostname -I) || true
if [ "$_IP" ]; then
  _logoutput "IP addresses: $_IP"
fi

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
	_logoutput "***** restarting network"
	_logoutput "$(ip link show)"
	_logoutput "$(nmcli device status)"
	_logoutput "$(iwconfig wlan0)"
	
	_logoutput "$($NETRESTARTCMD)"
	exit 1
else
	_logoutput "No Network Issues Detected"
	exit 0
fi
