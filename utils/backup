#!/bin/sh

# script/backup: Backup databases and/or media. 
#               Optionally specify which backup.
#               Optionally specify local, remote, or node-red locations.
#               Meant to be executed on host system.

cd "$(dirname "$0")/.."

#-- Database backup

cd ~/code/backup

#influx creates a directory of zipped files
docker exec influxdb influx backup /home/influxdb/backup/influxdb_bak
sudo tar -cvzf influxdb_$(date '+%Y-%m-%d_%H-%M').tar.gz influxdb_bak
sudo rm -rf influxdb_bak

#backup events database
tar -cvpzf events_sqlite_$(date '+%Y-%m-%d_%H-%M').tar.gz ~/code/nodered/data/tmdb

# transfer databases to server
# sudo rsync -azvv --progress -e ssh ~/code/backup/influxdb_2024-06-21_11-29.tar.gz NAME@SERVER:DB_DUMPS/
# sudo rsync -azvv --progress -e ssh ~/code/backup/events_sqlite_2024-06-03_08-40.tar.gz NAME@SERVER:DB_DUMPS/

#-- Images backup -- only do this attached locally (maximize data transfer)
#clips remote backup
#sudo rsync -azvv --progress -e ssh frigate/storage NAME@SERVER:DB_DUMPS/media/bak-$(date '+%Y-%m-%d')/frigate/
