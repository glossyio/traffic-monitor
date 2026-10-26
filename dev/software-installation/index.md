# Software Installation

Whether you [Build Your Own Device (DIY)](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/index.md) or buy a pre-built unit, these are the instructions to perform a fresh install.

### Preparation

Success

**Raspberry Pi OS 64-bit Lite install** is the recommended default and is the basis for the software. The 64-bit Full Install will provide a desktop environment and extra packages that are not used by the Traffic Monitor.

Find it on RPi Imager by navigating to *Operating System > Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit)*.

1. Install Raspberry Pi OS (64-bit lite) using [RPi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) (read the [RPi getting started](https://www.raspberrypi.com/documentation/computers/getting-started.html#installing-the-operating-system)).
1. You will need an SD card or microSD card reader on your host machine.
1. (*Recommended*) [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your WiFi credentials and username and password to access the device headless; i.e. SSH with no monitor or keyboard.
1. Insert the microSD card into the Raspberry Pi and boot.
1. Note: The first boot may take several minutes before it is fully online.

### Install the Traffic Monitor software

Warning

*An internet connection* is required to install system dependencies, build the required Podman containers, download drivers, and more. After installation, the traffic monitor can run fully offline.

Info

The Traffic Monitor software is installed via an [Ansible](https://github.com/ansible/ansible) deploy script. This allows you to perform a [local installation](#local-installation) or [remote installation](#remote-installation) from a host computer to 1 or more devices simultaneously!

#### Local installation

(*Most common installation method*)

1. [Connect to your device](https://docs.trafficmonitor.ai/dev/setup-guide/#1-connect-to-your-device) and executing the following commands via a terminal:
1. `sudo apt update && sudo apt install -y git`
1. `git clone https://github.com/glossyio/traffic-monitor`
1. `bash traffic-monitor/script/tmsetup.sh`
1. Follow instructions and restart when prompted.

#### Remote Installation

Install the TM software to 1 or more devices simultaneously using our Ansible deploy script. This allows you to deploy or update a whole fleet of Traffic Monitors with common configuration files in a single command!

Success

Before you can perform remote installation, ensure the following:

1. Your host machine is able to run `bash` commands (Linux or Mac)

1. Raspberry Pi OS is installed on each device

1. The traffic monitor device is running and online

1. You have the device IP address(es) or resolvable host name(s) from your host to the device(s)

1. On your host machine, download TM[1](#fn:1) OSS[2](#fn:2) software and set up any configurations you want to send:

1. `git clone https://github.com/glossyio/traffic-monitor`

1. Run the install script from your host machine with your device IP address(es) space-separated with `-H`, enter username specified on OS setup (needs to be the same across all devices) with `-l`, and prompt for password with `-k`:

1. `bash traffic-monitor/script/tmsetup.sh -H <ip_address> -l <ssh_username> -k`

1. Continue to [Deployment and Mounting Guide](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/index.md) and [Setup Guide](https://docs.trafficmonitor.ai/dev/setup-guide/index.md) for each device.

### Next Steps

1. Deploy your device: See the [Deployment and Mounting Guide](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/index.md).
1. Set up zones, location, and enable your sensors: See [Setup Guide](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).
1. Start capturing roadway usage data!

______________________________________________________________________

1. traffic monitor [↩](#fnref:1 "Jump back to footnote 1 in the text")
1. open source software [↩](#fnref:2 "Jump back to footnote 2 in the text")
