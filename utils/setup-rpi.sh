## Scripts to run for buster-p01
#assume lastest Raspberry PI OS Debian 12 (bookworm) and recommended software (full install)
# full install required for camera (lite version does not have H.264 codec for libcamera)
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



#alternative docker intall, for dev
# here https://raspberrytips.com/docker-on-raspberry-pi/
# or #https://docs.docker.com/engine/install/raspberry-pi-os/#install-using-the-convenience-script
curl -sSL https://get.docker.com | sh

sudo usermod -aG docker $USER

##-- /docker

##-- install Frigate

## Add Frigate Dockerfile
#create directories and config.yml
mkdir -p ~/code/frigate  #for config and files
mkdir -p ~/code/frigate/storage  #for media

# copy repo files to local folders
cp ../docker-frigate/docker-compose-frigate.yaml ~/code/frigate/docker-compose-frigate.yml
cp ../docker-frigate/frigate-config.yaml ~/code/frigate/config.yml

#docker compose up -n

##-- /frigate

##-- install go2rtc to use the Rpi camera

## Add go2rtc Dockerfile -- Don't use Dockerfile, will have to pass /dev/; instead, install locally
## background:  https://community.home-assistant.io/t/raspberry-pi-camera-as-dumb-h264-stream-for-frigate/565784/4
## alternatively use docker for libcamera, pass for now: https://github.com/raspberrypi/rpicam-apps/issues/270#issuecomment-1059372626
#create directories
mkdir -p ~/code/go2rtc

#for go2rtc config, https://github.com/AlexxIT/go2rtc#source-exec

#install go2rtc binary
sudo mkdir /var/lib/go2rtc

#sudo curl -O -L https://github.com/AlexxIT/go2rtc/releases/download/v1.8.2/go2rtc_linux_arm64
sudo curl -L https://github.com/AlexxIT/go2rtc/releases/download/v1.8.5/go2rtc_linux_arm64 -o /var/lib/go2rtc/go2rtc_linux_arm64_185
sudo chmod 755 /var/lib/go2rtc/go2rtc_linux_arm64_185
sudo chmod +x /var/lib/go2rtc/go2rtc_linux_arm64_185

echo \
  "# /etc/systemd/system/go2rtc_server.service
# to run: sudo systemctl stop/start/restart/enable/disable go2rtc_server

[Unit]
Description=go2rtc
After=network.target rc-local.service

[Service]
Restart=always
WorkingDirectory=/var/lib/go2rtc/
ExecStart=/var/lib/go2rtc/go2rtc_linux_arm64_185

[Install]
WantedBy=multi-user.target" | \
  sudo tee /etc/systemd/system/go2rtc_server.service > /dev/null
sudo chmod 644 /etc/systemd/system/go2rtc_server.service

echo \
"# /var/lib/go2rtc/go2rtc.yaml
streams:
  picam_h264: exec:rpicam-vid --camera 0 --mode 2304:1296 --framerate 15 --hdr --timeout 0 --nopreview --codec h264 --libav-video-codec h264 --libav-format h264 --inline -o -" | \
  sudo tee /var/lib/go2rtc/go2rtc.yaml > /dev/null
sudo chmod 744 /var/lib/go2rtc/go2rtc.yaml

#rpicam-vid settings
# rpicam-vid --list-cameras for modes available

sudo systemctl start go2rtc_server
sudo systemctl enable go2rtc_server

##-- /go2rtc

##-- install coral tpu drivers

#install EdgeTPU runtime library (??) https://coral.ai/docs/accelerator/get-started/#1-install-the-edge-tpu-runtime
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-get update

sudo apt-get install libedgetpu1-std

##-- /coral tpu drivers


##-- docker run node-red container
# this is OK for development, for Prod, may want Dockerfile to copy local resources only
#  this would avoid the need for /data volume to be mounted and keep flow/settings in a git repo
mkdir -p ~/code/nodered/data

# docker run -d \
#   --restart on-failure:3 \
#   -p 1880:1880 \
#   -p 1883:1883 \
#   -v ~/code/nodered/data:/data \
#   --device=/dev/ttyACM0 \
#   -u node-red:dialout \
#   --group-add dialout \
#   --name nodered \
#   nodered/node-red

cp ../docker-nodered/docker-compose-node-red.yaml ~/code/nodered/docker-compose-node-red.yml

# access via http://[IP]:1880
##-- /node-red


##-- docker compose build and start containers

docker compose \
   -f ~/code/frigate/docker-compose-frigate.yml \
   -f ~/code/nodered/docker-compose-node-red.yml \
   up --detach

