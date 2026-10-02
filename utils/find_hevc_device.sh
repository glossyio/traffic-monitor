#!/bin/bash
# Scan for /dev/media* devices and find one with model rpi-hevc-dec
for device in /dev/media*; do
    if udevadm info -a -n "$device" 2>/dev/null | grep -q 'ATTR{model}=="rpi-hevc-dec"'; then
        echo "$device"
        break
    fi
done
