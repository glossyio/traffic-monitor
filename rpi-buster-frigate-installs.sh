## Scripts to run for buster-p01
#update system
sudo apt-get update
sudo apt-get upgrade -y

##-- install docker / docker compose,
##      The Docker certificates and repos didn't work (why??), so use alternative, dev install script

##read more:  https://docs.docker.com/engine/install/raspberry-pi-os/
## Add Docker's official GPG key:
#sudo apt-get update
#sudo apt-get install ca-certificates curl gnupg
#sudo install -m 0755 -d /etc/apt/keyrings
#curl -fsSL https://download.docker.com/linux/raspbian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
#sudo chmod a+r /etc/apt/keyrings/docker.gpg

## Set up Docker's APT repository:
#echo \
#  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/raspbian \
#  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
#  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
#sudo apt-get update

#install
#sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin



#alternative intall, for dev
# here https://raspberrytips.com/docker-on-raspberry-pi/
# or #https://docs.docker.com/engine/install/raspberry-pi-os/#install-using-the-convenience-script
curl -sSL https://get.docker.com | sh

sudo usermod -aG docker $USER

##-- /docker

##-- install Frigate

## Add Frigate Dockerfile
#create directories and config.yml
mkdir ~/code/frigate  #for config and files
mkdir ~/code/frigate/storage  #for media
#download Dockerfile for Frigate
touch ~/code/frigate/config.yml
echo \
    "frigate config > ~/code/frigate/config.yml"

##-- /frigate

##-- install go2rtc to use the Rpi camera

## Add go2rtc Dockerfile -- Don't use Dockerfile, will have to pass /dev/; instead, install locally
## background:  https://community.home-assistant.io/t/raspberry-pi-camera-as-dumb-h264-stream-for-frigate/565784/4
#create directories
mkdir ~/code/go2rtc

#for go2rtc config, https://github.com/AlexxIT/go2rtc#source-exec


#install go2rtc binary

sudo mkdir /var/lib/go2rtc

#sudo curl -O -L https://github.com/AlexxIT/go2rtc/releases/download/v1.8.2/go2rtc_linux_arm64
sudo curl -L https://github.com/AlexxIT/go2rtc/releases/download/v1.8.2/go2rtc_linux_arm64 -o /var/lib/go2rtc/go2rtc
sudo chmod 755 /var/lib/go2rtc/go2rtc
sudo chmod +x /var/lib/go2rtc/go2rtc

echo \
  "# /etc/systemd/system/go2rtc_server.service
# to run: sudo systemctl stop/start/restart/enable/disable go2rtc_server

[Unit]
Description=go2rtc
After=network.target rc-local.service

[Service]
Restart=always
WorkingDirectory=/var/lib/go2rtc/
ExecStart=/bin/bash /var/lib/go2rtc/go2rtc

[Install]
WantedBy=multi-user.target" | \
  sudo tee /etc/systemd/system/go2rtc_server.service > /dev/null
sudo chmod 644 /etc/systemd/system/go2rtc_server.service

echo \
"# /var/lib/go2rtc/go2rtc.yaml
streams:
  picam_h264: exec:libcamera-vid --width 2304 --height 1296 --framerate 30 -t 0 --inline -o -" | \
  sudo tee /var/lib/go2rtc/go2rtc.yaml > /dev/null
sudo chmod 744 /var/lib/go2rtc/go2rtc.yaml

##-- /go2rtc

##-- install coral tpu drivers

#install EdgeTPU runtime library (??) https://coral.ai/docs/accelerator/get-started/#1-install-the-edge-tpu-runtime
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-get update

sudo apt-get install libedgetpu1-std

##-- /coral tpu drivers
