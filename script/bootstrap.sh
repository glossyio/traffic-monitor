#!/bin/sh

# script/bootstrap: Resolve all dependencies that the application requires to
#                   run.
# scripts based on https://github.com/github/scripts-to-rule-them-all

set -e

cd "$(dirname "$0")/.."

#assume lastest Raspberry PI OS Debian 12 (bookworm) and recommended software (full install)
# full install required for camera (lite version does not have H.264 codec for libcamera)
#update system
sudo apt-get update
#rpi recommends full-upgrade: https://www.raspberrypi.com/documentation/computers/os.html#manage-software-packages-with-apt
sudo apt full-upgrade -y

#set local timezone
sudo raspi-config nonint do_change_timezone America/Los_Angeles

##-- install docker / docker compose,
#alternative docker intall, for dev
# here https://raspberrytips.com/docker-on-raspberry-pi/
# or #https://docs.docker.com/engine/install/raspberry-pi-os/#install-using-the-convenience-script
echo "==> Installing docker…"
curl -sSL https://get.docker.com | sh

sudo usermod -aG docker $USER
##-- /docker

##-- install node-red as system service
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered) --confirm-install --confirm-pi --no-init
##-- /node-red

#install go2rtc binary
echo "==> Installing go2rtc…"

sudo mkdir /var/lib/go2rtc
sudo curl -L https://github.com/AlexxIT/go2rtc/releases/download/v1.8.5/go2rtc_linux_arm64 -o /var/lib/go2rtc/go2rtc_linux_arm64
sudo chmod 755 /var/lib/go2rtc/go2rtc_linux_arm64
sudo chmod +x /var/lib/go2rtc/go2rtc_linux_arm64
##-- /go2rtc


##-- install coral tpu drivers
#install EdgeTPU runtime library (??) https://coral.ai/docs/accelerator/get-started/#1-install-the-edge-tpu-runtime
echo "==> Installing Coral TPU drivers…"
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -

sudo apt update
sudo apt-get -y install libedgetpu1-std
##-- /coral tpu drivers

echo "==> Install screen for radar"
sudo apt-get -y install screen

#Mar 2024 - might need this for the RPi Camera GS if image is fipped vertically 180 and blue/red
#sudo rpi-update pulls/6027

echo "==> Rebooting system"
sudo reboot