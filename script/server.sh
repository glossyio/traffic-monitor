#!/bin/sh

# script/server: Launch the application and any extra required processes
#                locally.

set -e

cd "$(dirname "$0")/.."

# uncomment to ensure everything in the app is up to date.
#script/update

sudo systemctl start go2rtc_server
sudo systemctl enable go2rtc_server

# node-red nodes install/reinstall
npm install --unsafe-perm --no-update-notifier --no-fund --only=production --prefix ~/.node-red/

sudo systemctl start nodered.service
sudo systemctl enable nodered.service

##-- docker compose build and start containers
docker compose -f ~/code/compose.yaml up --detach

# access frigate via http://[IP]:5000
# access node-red via http://[IP]:1880