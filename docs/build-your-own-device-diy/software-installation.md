---
description: Software installation for the Traffic Monitor.
---

# Software Installation

Whether you [.](./ "mention") or buy a pre-built unit, these are the instructions to perform a fresh install.

### Preparation

{% hint style="info" %}
**Raspberry Pi OS 64-bit Lite install** is the recommended default; however, RPi OS 64-bit Full install will give you a desktop environment and other packages. Find it on RPi Imager by navigating to _Operating System > Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit)_.
{% endhint %}

1. Install [Raspberry Pi OS](https://www.raspberrypi.com/software/) (64-bit lite) using [RPi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager).
   * Recommended: [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your WiFi credentials and username and password to access the device headless; i.e. SSH with no monitor or keyboard.
2. Insert the microSD card and boot up the Raspberry Pi device.&#x20;
   * Note: The first boot may take a few minutes before it is fully online.

### Install the Traffic Monitor software

{% hint style="warning" %}
_An internet connection_ is required to install system dependencies, build the required Docker containers, download drivers, and more.  After installation, the traffic monitor can run fully offline.
{% endhint %}

{% hint style="info" %}
The Traffic Monitor software is installed via an [Ansible](https://github.com/ansible/ansible) deploy script.  This allows you to perform a [local installation](software-installation.md#local-installation) or [remote installation](software-installation.md#remote-installation) from a host computer to 1 or more devices simultaneously!
{% endhint %}

#### Local installation

1. [Connect to your device](../setup-guide.md#id-1.-connect-to-your-device) and executing the following commands via a terminal:
   1. `sudo apt update && sudo apt install -y git` &#x20;
   2. `git clone https://github.com/glossyio/traffic-monitor`&#x20;
   3. `bash traffic-monitor/script/tmsetup.sh`
2. Follow instructions and restart when prompted. &#x20;

#### Remote Installation

Install the TM software to 1 or more devices simultaneously using our Ansible deploy script. This allows you to deploy or update a whole fleet of Traffic Monitors with common configuration files in a single command!

{% hint style="success" %}
Before you can perform remote installation, ensure the following:&#x20;

1. Your host machine is able to run `bash` commands (Linux or Mac)
2. Raspberry Pi OS is installed on each device
3. the device is running and online
4. you have the device IP address or resolvable host name from your host to the device
{% endhint %}

1. On your host machine, download TM[^1] OSS[^2] software and set up any configurations you want to send:&#x20;
   1. `git clone https://github.com/glossyio/traffic-monitor`
2. Run the install script from your host machine with your device IP address(es), enter username specified on OS setup (needs to be the same across all devices, and prompt for password): &#x20;
   1. `bash traffic-monitor/script/tmsetup.sh -H <ip_address> -l <ssh_username> -k`&#x20;
3. Continue to [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention") and [setup-guide.md](../setup-guide.md "mention") for each device.

### Next Steps

1. Deploy your device: See the [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention").
2. Set up zones, location, and enable your sensors: See [setup-guide.md](../setup-guide.md "mention").
3. Start capturing roadway usage data!

[^1]: traffic monitor

[^2]: open source software
