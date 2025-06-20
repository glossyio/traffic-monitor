---
description: Software installation for the Traffic Monitor.
---

# Software Installation

Whether you [.](./ "mention") or buy a pre-built unit, these are the instructions to start from scratch with the open source Traffic Monitor:

1. Assemble your device (see [recommended-hardware.md](../recommended-hardware.md "mention")).
2. Install [Raspberry Pi OS](https://www.raspberrypi.com/software/) (Full Install) Bookworm (latest).
   * Full Install required for all components to run properly. Lite is missing H.264 codec for libcamera.
   * Recommend to [Install using Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) instructions and follow the [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your Wi-Fi credentials and username and password to access the device headless (no monitor or keyboard).
   * The first boot may take a few minutes before it is fully online.
3. Access your Raspberry Pi: See [#connect-to-your-device](../setup-guide.md#connect-to-your-device "mention").
4. Install the Traffic Monitor software:
   1. Run `git clone https://github.com/glossyio/traffic-monitor` into your home folder (or any folder)
   2. Run `cd traffic-monitor`
   3. Run `sudo chmod +x script/*` to enable scripts
   4. Run `./script/bootstrap` to fulfill dependencies. _Note_: System will reboot after this script.
   5. After reboot, log into the device and `cd traffic-monitor` to continue.
   6. Run `./script/setup` to set up project in an initial state
   7. Run `./script/server` to start the application
      * `./script/update` is not required on initial setup but may be used if you change Docker configurations. This _does not_ yet automatically update the traffic monitor.
5. Deploy your device: See the [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention").
6. Set up zones, location, and enable your sensors: See [setup-guide.md](../setup-guide.md "mention").
7. Start capturing roadway usage data!

