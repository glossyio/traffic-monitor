---
description: Traffic Monitor Node-RED configuration logic
---

# Node-RED Config

{% hint style="info" %}
This page is for the Traffic Monitor -specific configuration of the Node-RED flows. This controls much of the logic and flow for the traffic monitor but does not control other applications such as Frigate or the operating system.
{% endhint %}

{% hint style="info" %}
See [frigate-config.md](frigate-config.md "mention") for controlling object detection parameters.
{% endhint %}

## Environment File

The environment file defines variables that can be used during Node-RED start-up in the [settings file](https://nodered.org/docs/user-guide/runtime/settings-file) and within a flows' node properties.

A sample script can be found at [node-red-project/environment](https://github.com/glossyio/traffic-monitor/blob/main/node-red-project/environment).

The environment file is loaded by the `systemd` service `node-red.service` that is set up during by the [Node-RED Rapsberry Pi Install script](https://nodered.org/docs/getting-started/raspberrypi). It shall be located in the user node-red directory, by default at `~/.node-red/environment`.  Changes to the environment file must be applied by restarting the Node-RED service by executing the command `node-red-restart` in the terminal.

```sh
########
# This file contains node-red environment variables loaded by node-red.service
#   Read more at https://nodered.org/docs/user-guide/environment-variables
#     and https://fedoraproject.org/wiki/Packaging:Systemd
#  
# This file shall be located at the root node-red directory, usually `~/.node-red`
#   this file is loaded by `systemd`, changes can be applied 
#   by running the command `node-red-restart` in the terminal
#   read more at https://nodered.org/docs/getting-started/raspberrypi
#
# Uses:
#   - variables can be used in settings.js by calling `process.env.ENV_VAR`
#   - node property can be set by calling `${ENV_VAR}
#
########

# traffic monitor open source software release version
TM_VERSION='0.3.0'

# used in settings.js for credentialSecret 
NODE_RED_CREDENTIAL_SECRET='myNodeRED1234'

# database locations, relative to user directory defined in settings.js
#  will be relative path to store SQLite databases
TM_DATABASE_PATH_TMDB='code/nodered/db/tmdb.sqlite'

# mqtt broker for incoming Frigate events 
#  Settings below set up the aedes broker node
TM_MQTT_BROKER_HOST='localhost'
TM_MQTT_BROKER_PORT='1883'
# mqtt user, leave blank for no authentication
TM_MQTT_BROKER_USERNAME=''
# mqtt password, leave blank for no authentication
TM_MQTT_BROKER_PASSWORD=''

# defines system USB serial port for radar
# run `ls -lat /sys/class/tty/ttyACM*` to list devices
TM_RADAR_SERIAL_PORT_00='/dev/ttyACM0'
TM_RADAR_SERIAL_PORT_01='/dev/ttyACM1'
TM_RADAR_SERIAL_PORT_02='/dev/ttyACM2'
TM_RADAR_SERIAL_PORT_03='/dev/ttyACM3'
```

## Config File

The Traffic Monitor Node-RED config file changes definitions to various services and functionality.&#x20;

The config file is loaded whenever the TM flows restart.  It is located in the user node-red directory,`~/.node-red/config.yml`.

{% hint style="info" %}
It is _not necessary_ to copy this full configuration file. Default values are specified below.
{% endhint %}

```yml
########
# This file contains configuration settings executed by node-red
# Note: Comments will be removed by updates from node-red
########

# Optional: IoT hub backend integration
thingsboard:
    # Optional: enable connection to backend thingsboard server (default: shown below)
    enabled: false
    # Required: host name, without protocol or port number
    host: tb.server.com
    # Required: thingsboard telemetry protocol (default: shown below), 
    # NOTE: only http(s) currently supported, mqtt coming soon
    #  see https://thingsboard.io/docs/reference/protocols/
    protocol: https
    # Optional: port, common settings: https=443, http=80, mqtt=1883
    # Check with your ThingsBoard admin for settings
    port: 443
    # Optional: API key for device 
    # Note: (Future) if already provisioned, will be assigned based on provisionDeviceKey and secret
    access_token:
    # Optional: future use for auto-provisioning (RPiSN)
    # provisionDeviceKey: 
    # Optional: future use for auto-provisioning (manual)
    # provisionDeviceSecret: 

# Optional: deployment location details
# Note: May be used to determine device placement on maps
# NOTE: Can be overridden at the sensors level, top-level values will cascade down
deployment:
    # NOTE: for address-level accuracy, recommend at least 4 digits after the decimal
    # Optional: Latitude in decimal degrees format; e.g. 45.5225
    lat:
    # Optional: Longitude in decimal degrees format; e.g. -122.6919
    lon:
    # Optional: cardinal (N, S, E, W) or ordinal (NE, NW, SE, etc.) direction the camera/radar is facing 
    # Note: For bearing, match the roadway traffic direction
    bearing:

sensors:
    # Optional: if used, must match the Frigate camera name(s)
    # if not set, no cameras will be used
    cameras:
        # camera name must match Frigate configuration camera names
        picam_h264:
            # Optional Enable/disable the camera (default: shown below).
            # if disabled, any Frigate events for specified camera will be ignored
            # Note: this will not impact Frigate's system
            enabled: false
            # Optional: define the radar co-located with camera to associate speeds
            # camera and radar direction and field of view (FOV) should match
            # Note: name needs to match one defined in `radars` section
            # Note: A single radar may be attached to multiple cameras
            camera_radar: TM_RADAR_SERIAL_PORT_00

    # Optional: used to specify what radars are enabled for speed/direction and detection
    radars:
        # Note: Names must match those defined in the node-red environment file
        # Names are used to associate readings with cameras and other sensors
        TM_RADAR_SERIAL_PORT_00:
            # Optional: Enable/disable the radar (default: shown below).
            enabled: false

    # Optional: used to specify air quality monitor sensor name(s)
    # Note: air quality configuration file is separate from the node-red config, based on the aq device
    airquality_monitors:
        # Required: aq sensor name must match AQ configuration -defined MQTT topic middle element (second element)
        sensorname01:
            # Optional: Enable/disable the AQ sensor payloads (default: shown below).
            enabled: false
            # Required: mqtt topic to subscribe for incoming full-payload telemetry from AQ sensor
            #  must be last element in mqtt topic defined in AQ configuration
            mqtt_topic_incoming: readings

time:
    # Optional: Set a timezone to use in the UI (default: use browser local time)
    # NOTE: shall be in unix tz format: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
    #  this will also set the timezone for the entire system
    timezone: America/Los_Angeles
    # Optional: For internet-connected deployments, sync using `timedatectl set-npt` (default: shown below)
    # Note: for offline deployments, time will stop whenever power is disconnected
    npt_set: false
```

