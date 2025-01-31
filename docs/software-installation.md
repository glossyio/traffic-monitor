---
description: Software installation for the Traffic Monitor.
---

# Software Installation

Whether you [build-your-own-device-diy](build-your-own-device-diy/ "mention") or buy a pre-made unit, these are the instructions to start from scratch with the open source Traffic Monitor:

1. Assemble your device (see [recommended hardware](recommended-hardware.md) ⚒️).
2. Install [Raspberry Pi OS](https://www.raspberrypi.com/software/) (Full Install) Bookworm (latest).
   * Full Install required for all components to run properly. Lite is missing H.264 codec for libcamera.
   * Recommend to [Install using Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) instructions and follow the [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your Wi-Fi credentials and username and password to access the device headless (no monitor or keyboard).
3. Insert the microSD card and start your device
   * First boot may take a few minutes before it is fully online
4. [Remotely access your device](https://www.raspberrypi.com/documentation/computers/remote-access.html#introduction-to-remote-access) (recommend using SSH) and login to your Raspberry Pi
   * Recommend use IP Address in case your router doesn't recognize the hostname you set during setup.
5. Run `git clone https://github.com/glossyio/traffic-monitor` into your home folder (or any folder)
6. Run `cd traffic-monitor`
7. Run `sudo chmod +x script/*` to enable scripts
8. Run `./script/bootstrap` to fulfill dependencies. _Note_: System will reboot after this script.
9. After reboot, log into the device and `cd traffic-monitor` to continue.
10. Run `./script/setup` to set up project in an initial state
11. Run `./script/server` to start the application
    * `./script/update` is not required on initial setup but may be used if you change Docker configurations. This _does not_ yet automatically update the traffic monitor.
12. Access the application at the following URLs (check container status with `docker ps`):
    1. `http://<device_ip_address>:1880/ui` is your primary device dashboard, use it to ensure it is capturing events (Node-Red dashboard)
    2. `http://<device_ip_address>:5000` to view the Frigate interface and make any configuration changes specific to your deployment
13. Mount your device in a place it can capture the entire roadway in the mounting guide (coming soon).
14. [Configure your device](https://github.com/glossyio/traffic-monitor#configuration)
15. Start capturing roadway usage data!
