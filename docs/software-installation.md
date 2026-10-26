---
description: Image a microSD card with Raspberry Pi OS and run the Traffic Monitor installer, on the device or from another computer.
---

# Install the software

The Traffic Monitor runs on a Raspberry Pi 5 with Raspberry Pi OS Lite (64-bit). One installer script sets up the operating system, detects the camera, radar, and AI accelerator, builds the containers on the device, and reboots when it needs to.

## Prepare the card

1. Open [Raspberry Pi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) on your computer, with the microSD card in a card reader.
2. Choose **Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit)**. The full desktop image works but installs software the Traffic Monitor doesn't use.
3. In [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options), set a hostname, a username and password, your Wi-Fi network, and turn on SSH. The hostname becomes the device's address on your network: `http://<hostname>.local/`.
4. Write the card, put it in the Raspberry Pi, and power it on. The first boot takes a few minutes.

## Install on the device

The device needs an internet connection during the install. Afterwards it runs offline.

Connect over SSH with the username and hostname you chose:

```bash
ssh <username>@<hostname>.local
```

Then download the repository and run the installer:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/glossyio/traffic-monitor
bash traffic-monitor/script/tmsetup.sh
```

The installer asks for your password when it needs administrator rights. A first install takes 30 minutes or more. Building Frigate's container image compiles ffmpeg on the device, which alone takes about 20 minutes with little output, so leave it running.

Near the end, the installer asks to reboot. The reboot finishes installing the driver for the AI accelerator it found and starts the services. After it, open `http://<hostname>.local/` and continue with [First-time setup](setup-guide.md).

The installer's flags, such as a different install folder or time zone, are listed in [Installer options](reference/tmsetup.md).

## Install from another computer

The same script can install or update one or more devices over SSH from a Linux or Mac computer. Each device needs Raspberry Pi OS, a network connection, and an address you can reach.

```bash
git clone https://github.com/glossyio/traffic-monitor
bash traffic-monitor/script/tmsetup.sh -H <address>[,<address>] -l <username> -k -K
```

| Flag | Meaning |
|---|---|
| `-H` | The devices' hostnames or IP addresses, separated by commas |
| `-l` | The username you set when imaging the cards. It must be the same on every device. |
| `-k` | Ask for the SSH password |
| `-K` | Ask for the password for administrator rights. Raspberry Pi OS requires it. |

Remote devices reboot by themselves when the install needs it.

## Next steps

1. [Choose a site and mount](deployment-and-mounting-guide.md) the device.
2. [First-time setup](setup-guide.md): turn on detection, adjust the zones, and record the location.
