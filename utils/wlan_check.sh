#!/bin/bash
# Script will check if wlan0 is operating nominally and if not, reset the device

ERROR=false
LOGFILE=/var/log/wlan_check.log
DOMAINADDR='duckduckgo.com'
GWADDR=$(ip route show | grep "^default" | cut -d\  -f3)
PUBNSADDRS=("8.8.8.8","1.1.1.1","9.9.9.9")
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
_logoutput "==============================================================================="
_logoutput "Starting wlan_check"

_logoutput "ThingsBoard: $DOMAINADDR"
_logonerror "host $DOMAINADDR"
_logonerror "ping -c2 $DOMAINADDR"

_logoutput "Gateway: $GWADDR"
_logonerror "ping -c2 $GWADDR"

for ns in $(grep "^nameserver" /etc/resolv.conf|tr -s " " | cut -d\  -f2 | tr "\n" " ")
do
	_logoutput "Nameserver: $ns"
	_logonerror "ping -c2 $ns"
done

for pubns in ${PBNSADDRS[@]}
do
	_logoutput "Nameserver: $pubns"
	_logonerror "ping -c2 $pubns"
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
