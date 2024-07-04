# rpi-buster - Traffic Monitoring Solution

## Get Started

1. Install Raspberry Pi OS Bookworm (Full Install). Full Install required for all components to run properly. Lite is missing H.264 codec for libcamera.
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
1. SSH or log into your Raspberry Pi
   - Wait a minute until the LED next to the power connector is solid green
   - Your TM should be at "_device name_.local". If not:
     - If you run a VPN, turn it off
     - Check your router to see whether your TM is online
     - Find your TM's IP address in your router's tables and access the TM by IP address instead of domain name
     - When you re-image your TM, ssh will complain about an incorrect "fingerprint". The easiest solution is to delete the old fingerprint from the file that is identified in the error message.
1. `git clone https://github.com/glossyio/rpi-buster` into your home folder (or any folder)
1. `cd rpi-buster`
1. Run `sudo chmod +x script/*` to enable scripts
1. Run `./script/bootstrap` to fulfill dependencies. Note: System will reboot after Docker install
1. Run `./script/setup` to set up project in an initial state
1. Run `./script/update` as a matter of good practice to update any application ahead of booting
1. Run `./script/server` to start the application
1. Run `./script/test` to to run test suite of the application (not currently enabled)
1. `./script/cibuild` is used from the continuous integration server (not currently enabled)
1. Go to `http://<rpi_ip_address>:5000` to view the Frigate interface and make any configuration changes specific to your deployment. If the camera shows nothing, check the configuration:

   - Make sure the camera is enabled
   - If necessary, edit the input path to include your TM's domain name or IP address, for example: `- path: rtsp://192.168.0.47:8554/picam_h264`
   - Once the camera is working, turn on detection (detect/enabled)

1. Start capturing traffic data!

All captured images and video will be stored in `~/code/frigate/storage` on the host by default.

## Hardware componets

Utilize commidity consumer hardware to enable speed/direction and object detection.

- Raspberry Pi 5 - The RPi 4B does not have the power requirements on the peripherals (USB) for radar and TPU
- OmniPreSence OPS-243 Radar - provides accurate radar-based speed/direction detection
- Google Coral TPU - AI/ML co-processor capable of 100+ FPS with millisecond inference time
- Raspberry Pi Global Shutter Camera - specialized for ML computer vision tasks

## Ports

Once the TM is running, you can access its functions at these ports:
| Port | Function | Description |
|------|----------|-------------|
|5000 | Frigate | Camera images and events|
|http://192.168.0.47:1880/u | TM Dashboard | Summary statistics and detected object speeds |
| 1984 | go2rtc |Camera status|
|1880 | NodeRed Editor | View and edit workflow structure |
