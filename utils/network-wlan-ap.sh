#!/bin/sh

# script/network-wlan-ap: Turn Traffic Monitor into a wireless access Point 
#               Turns on/off wireless access point
#               Allows other devices in remote deployments without a network to connect
# https://www.raspberrypi.com/documentation/computers/configuration.html#host-a-wireless-network-on-your-raspberry-pi
# See examples: https://networkmanager.dev/docs/api/latest/nmcli-examples.html
    # More examples: https://www.golinuxcloud.com/nmcli-command-examples-cheatsheet-centos-rhel/ 

#enable hotspot
sudo nmcli device wifi hotspot ssid <example-network-name> password <example-password>

#disable hotspot
#sudo nmcli device disconnect wlan0

#to get hotspot to run on restart...
# sudo -H nano /etc/NetworkManager/system-connections/Hotspot.nmconnection
# look for `autoconnect=false` and change to true

#list available wifi aps
#nmcli device wifi list

#connect to a password-protected wifi network
#nmcli device wifi connect "$SSID" password "$PASSWORD"

#turn on normal network mode
#sudo nmcli device up wlan0

#convenient field values retrieval for scripting
#nmcli -g ip4.address connection show my-con-eth0

#create ethernet static IP address
#sudo nmcli con add con-name eth-static type ethernet ifname eth0 ipv4.method manual ipv4.address 192.168.1.15/24 ipv4.gateway 192.168.1.1
