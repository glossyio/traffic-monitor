---
description: Software installation for the Traffic Monitor.
---

# Software Installation

Whether you [Build Your Own Device (DIY)](build-your-own-device-diy/README.md) or buy a pre-built unit, these are the instructions to perform a fresh install.

### Preparation

!!! success

    **Raspberry Pi OS 64-bit Lite install** is the recommended default and is the basis for the software. The 64-bit Full Install will provide a desktop environment and extra packages that are not used by the Traffic Monitor.

    Find it on RPi Imager by navigating to _Operating System > Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit)_.

1. Install Raspberry Pi OS (64-bit lite) using [RPi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) (read the [RPi getting started](https://www.raspberrypi.com/documentation/computers/getting-started.html#installing-the-operating-system)).
   * You will need an SD card or microSD card reader on your host machine.
   * (_Recommended_) [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your WiFi credentials and username and password to access the device headless; i.e. SSH with no monitor or keyboard.
2. Insert the microSD card into the Raspberry Pi and boot.
   * Note: The first boot may take several minutes before it is fully online.

### Install the Traffic Monitor software

!!! warning

    _An internet connection_ is required to install system dependencies, build the required Podman containers, download drivers, and more.  After installation, the traffic monitor can run fully offline.

!!! info

    The Traffic Monitor software is installed via an [Ansible](https://github.com/ansible/ansible) deploy script.  This allows you to perform a [local installation](#local-installation) or [remote installation](#remote-installation) from a host computer to 1 or more devices simultaneously!

#### Local installation

(_Most common installation method_)

1. [Connect to your device](setup-guide.md#1-connect-to-your-device) and executing the following commands via a terminal:
   1. `sudo apt update && sudo apt install -y git` 
   2. `git clone https://github.com/glossyio/traffic-monitor`
   3. `bash traffic-monitor/script/tmsetup.sh`
2. Follow instructions and restart when prompted. 

#### Remote Installation

Install the TM software to 1 or more devices simultaneously using our Ansible deploy script. This allows you to deploy or update a whole fleet of Traffic Monitors with common configuration files in a single command!

!!! success

    Before you can perform remote installation, ensure the following:

    1. Your host machine is able to run `bash` commands (Linux or Mac)
    2. Raspberry Pi OS is installed on each device
    3. The traffic monitor device is running and online
    4. You have the device IP address(es) or resolvable host name(s) from your host to the device(s)

1. On your host machine, download TM[^1] OSS[^2] software and set up any configurations you want to send:
   1. `git clone https://github.com/glossyio/traffic-monitor`
2. Run the install script from your host machine with your device IP address(es) space-separated with `-H`, enter username specified on OS setup (needs to be the same across all devices) with `-l`, and prompt for password with `-k`: 
   1. `bash traffic-monitor/script/tmsetup.sh -H <ip_address> -l <ssh_username> -k`
3. Continue to [Deployment and Mounting Guide](deployment-and-mounting-guide.md) and [Setup Guide](setup-guide.md) for each device.

### Next Steps

1. Deploy your device: See the [Deployment and Mounting Guide](deployment-and-mounting-guide.md).
2. Set up zones, location, and enable your sensors: See [Setup Guide](setup-guide.md).
3. Start capturing roadway usage data!

[^1]: traffic monitor

[^2]: open source software
