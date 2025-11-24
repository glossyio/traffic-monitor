---
description: Software installation for the Traffic Monitor.
---

# Software Installation

Whether you [.](./ "mention") or buy a pre-built unit, these are the instructions to perform a fresh install:

### Preparation

1. Install [Raspberry Pi OS](https://www.raspberrypi.com/software/) (lite Install) of Bookworm (latest).
   * Lite install is the recommended default, but Full install will give you a desktop environment and other packages.&#x20;
   * Recommend using [RPi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) instructions and follow the [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your WiFi credentials and username and password to access the device headless; i.e. SSH with no monitor or keyboard.
   * The first boot may take a few minutes before it is fully online.
2. Access your Raspberry Pi via SSH credentials from step above: See [#connect-to-your-device](../setup-guide.md#connect-to-your-device "mention").

### Install the Traffic Monitor software

The Traffic Monitor software is installed via an [Ansible](https://github.com/ansible/ansible) deploy script.  This allows us to offer both [local installation](software-installation.md#local-installation) on the device or [remote installation](software-installation.md#remote-installation) from a host computer to 1 or more devices!

#### Local installation

1. Install by [connecting to your device](../setup-guide.md#id-1.-connect-to-your-device) and executing the following commands via a terminal:
   1. `sudo apt update && sudo apt install`&#x20;
   2. `git clone https://github.com/glossyio/traffic-monitor`&#x20;
   3. `bash traffic-monitor/script/tmsetup.sh`

#### Remote Installation

You can install the TM software to 1 or more devices simultaneously using our Ansible deploy script. This gives you to deploy to a whole fleet with common configuration files in a single command!

{% hint style="info" %}
Before you can perform remote installation, ensure the following:&#x20;

1. Your host machine is able to run `bash` commands (Linux or Mac)
2. Raspberry Pi OS is installed on each device
3. the device is running and online
4. you have the device IP address or resolvable host name from your host machine to the device
{% endhint %}

1. On your host machine, download TM OSS software and set up any configurations you want to send:&#x20;
   1. `git clone https://github.com/glossyio/traffic-monitor`
2. Run the install script from your host machine with your device IP address(es), enter username specified on OS setup (needs to be the same across all devices, and prompt for password): &#x20;
   1. `bash traffic-monitor/script/tmsetup.sh -H <ip_address> -l <ssh_username> -k`&#x20;
3. Continue to [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention") and [setup-guide.md](../setup-guide.md "mention") for each device.

### Next Steps

1. Deploy your device: See the [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention").
2. Set up zones, location, and enable your sensors: See [setup-guide.md](../setup-guide.md "mention").
3. Start capturing roadway usage data!
