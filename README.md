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
1. Mount your unit in a place it can capture the entire roadway in the mounting guide (coming soon).
1. Start capturing roadway usage data!

## Hardware componets
This setup uses commidity, consumer hardware to enable object detection and speed/direction measurement:

- Raspberry Pi 5 - The RPi 4B does not have the power requirements on the peripherals (USB) for radar and TPU
- OmniPreSence OPS-243 Radar - provides accurate radar-based speed/direction detection
- Google Coral TPU - AI/ML co-processor capable of 100+ FPS with millisecond inference time
- Raspberry Pi Global Shutter Camera - specialized for ML computer vision tasks

## Installation and Setup Tips
Install Raspberry Pi OS:
   - Use the [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
     - You will need a mini-SD card reader
     - Ignore any error messages about the "drive" from your operating system
   - "Choose Device": Raspberry Pi 5
   - "Choose OS": Raspberry Pi OS (64-bit)
   - "Choose Storage": select your mini-SD card reader
   - On the next prompt, the first time you setup your TM, select "Edit Settings"
     - On the "General" tab, set your device name, WIFI parameters, define a username and password for accessing the TM remotely, and set your locale
     - On the "Services" tab, select "Use password authentication"
   - Back on the "Use OS Customization?" prompt, hit "Yes" to start writing the image.
     - If the Imager produces an error message, try a second time.
     - Imaging takes 5 or more minutes

If the Frigate camera shows nothing, check the configuration:
   - Review the [Frigate Camera Setup](https://docs.frigate.video/frigate/camera_setup) documentation.
   - Make sure the camera is enabled
   - If necessary, edit the Frigate `camera > path` to include your hostname or IP address, for example: `- path: rtsp://<rpi_ip_address>:8554/picam_h264`
   - Once the camera is working, turn on detection (detect/enabled)