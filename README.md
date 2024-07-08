# Traffic Monitor
The Traffic Monitor is an open source smart city traffic monitoring software built with commodity hardware to capture holistic roadway usage. Utilizing machine learning object detection and Doppler radar, it counts pedestrians, bicycles, and cars and measures vehicle speeds.

Use cases and capabilities:
- (coming soon) Crowd-sourced public dashboards to display roadway utiliztion.
- Reporting roadway utilization - counting cars, bicycles, pedestrians, and more.
- Capturing speeding drivers - measuring speeds, capturing image and video of event.
- Permanent, long-term deployment on roadways to monitor roadway usage.
- Temporary, remote deployments utilizing the low-power footprint and batteries.
-  [Frigate](https://github.com/blakeblackshear/frigate) provides the object detection capabilities

## Get Started
1. Assemble your unit (see Hardware below).
1. Install [Raspberry Pi OS](https://www.raspberrypi.com/software/) (Full Install) Bookworm (latest). 
    - Full Install required for all components to run properly. Lite is missing H.264 codec for libcamera.
    - Recommend to [Install using Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-using-imager) instructions and using [OS customization](https://www.raspberrypi.com/documentation/computers/getting-started.html#advanced-options) to set up your Wi-Fi credentials and username and password to access headless.
1. Insert the card and start your Raspberry Pi
    - First boot may take a few minutes before it is fully online
1. [Remotely access your Pi](https://www.raspberrypi.com/documentation/computers/remote-access.html#introduction-to-remote-access) (recommend using SSH) and login to your Raspberry Pi
    - Recommend use IP Address in case your router doesn't recognize the hostname you set during setup.
1. `git clone https://github.com/glossyio/traffic-monitor` into your home folder (or any folder)
1. `cd traffic-monitor` 
1. Run `sudo chmod +x script/*` to enable scripts
1. Run `./script/bootstrap` to fulfill dependencies. Note: System will reboot after Docker install
1. Run `./script/setup` to set up project in an initial state
1. Run `./script/server` to start the application
    - `./script/update` is not required on initial setup but may be used if you change Docker configurations
1. Once your docker containers start up (check with `docker ps`), access the application at the following URLs:
    1. `http://<rpi_ip_address>:1880/ui` is your primary device dashboard, use it to ensure it is capturing events
    1. `http://<rpi_ip_address>:5000` to view the Frigate interface and make any configuration changes specific to your deployment
1. Start capturing roadway usage data!

## Hardware componets
This setup uses commidity, consumer hardware to enable object detection and speed/direction measurement:

- [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) 
    - Note: The RPi 4B does not meet the power requirements on the peripherals (USB) for the TPU and radar, so it is not recommended for this setup.
- [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - provides accurate radar-based speed/direction detection
- [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) or [Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for object detection
- [Google Coral USB Accelerator](https://coral.ai/products/accelerator) TPU - AI/ML co-processor capable of 100+ FPS with millisecond inference time. This is supported natively in [Frigate](https://github.com/blakeblackshear/frigate).
- Mounting board and external enclosure need to be custom made at the moment, instructions coming soon.