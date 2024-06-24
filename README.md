# rpi-buster - Traffic Monitoring Solution

## Get Started
1. Install Raspberry Pi OS Bookworm (Full Install). Full Install required for all components to run properly. Lite is missing H.264 codec for libcamera.
1. SSH or log into your Raspberry Pi
1. `git clone https://github.com/glossyio/rpi-buster` into your home folder (or any folder)
1. `cd rpi-buster` 
1. Run `sudo chmod +x script/*` to enable scripts
1. Run `./script/bootstrap` to fulfill dependencies. Note: System will reboot after Docker install
1. Run `./script/setup` to set up project in an initial state
1. Run `./script/update` as a matter of good practice to update any application ahead of booting
1. Run `./script/server` to start the application
1. Run `./script/test` to to run test suite of the application (not currently enabled)
1. `./script/cibuild` is used from the continuous integration server (not currently enabled)
1. Go to `http://<rpi_ip_address>:5000` to view the Frigate interface and make any configuration changes specific to your deployment
1. Start capturing traffic data!

All captured images and video will be stored in `~/code/frigate/storage` on the host by default.

## Hardware componets
Utilize commidity consumer hardware to enable speed/direction and object detection.

- Raspberry Pi 5 - The RPi 4B does not have the power requirements on the peripherals (USB) for radar and TPU
- OmniPreSence OPS-243 Radar - provides accurate radar-based speed/direction detection
- Google Coral TPU - AI/ML co-processor capable of 100+ FPS with millisecond inference time
- Raspberry Pi Global Shutter Camera - specialized for ML computer vision tasks
