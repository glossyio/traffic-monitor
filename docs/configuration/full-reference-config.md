---
description: Traffic Monitor Node-RED configuration logic
---

# Full Reference Config

{% hint style="info" %}
This page is for the Traffic Monitor -specific configuration of the Node-RED flows. This controls much of the logic and flow for the traffic monitor but does not control other applications such as Frigate or the operating system.
{% endhint %}

For Frigate configuration file, refer to the official [Frigate Reference Config](https://docs.frigate.video/configuration/reference).

## Reference Config

{% hint style="warning" %}
It is _not recommended_ to copy this full configuration file. See [traffic-monitor-configuration.md](traffic-monitor-configuration.md "mention") for applicable samples.&#x20;

Configuration options and defaults may change at any time.
{% endhint %}



<pre class="language-yaml"><code class="lang-yaml">thingsboard:
    enabled: True
    host: tb.server.com
    # Required: http (default: shown below), mqtt (coming soon)
    # NOTE: see https://thingsboard.io/docs/reference/protocols/
    protocol: http
    port: 80
    # Optional: 
    # Note: (Future) if already provisioned, will be assigned based on provisionDeviceKey
    api_key: 
    # Optional: future use for auto-provisioning (RPiSN)
    # provisionDeviceKey: 
    # Optional: future use for auto-provisioning (manual)
    # provisionDeviceSecret: 

 #Optional: Database configuration
database:
    # the path to store the SQLite DB (default: shown below)
    # tmdb contains events (object detection), deployment (location), other core tables
    tmdb_path: code/nodered/db/tmdb.sqlite
    # radar contains all radar-based detections
    radar_path: code/nodered/db/radar.sqlite

# Optional: (Required for object detection) node-RED mqtt broker for incoming Frigate events 
# Note: Settings below set up the aedes broker node (if enabled) AND subscriber/publisher nodes
mqtt_broker:
    # Optional: (default: shown below)
    # enabled_server: True
    # Required: MQTT server address
    # NOTE: if enabled_server is false, this shall point to external broker
    host: localhost
    # Optional: MQTT server port
    port: 1883
    # Optional: user, leave blank for no authentication
<strong>    # NOTE: MQTT user can be specified with an environment variable.
</strong>    username:
<strong>    # Optional: password, leave blank for no authentication
</strong>    # NOTE: MQTT password can be specified with an environment variable.
    password:

# Optional: Doppler radar config    
radar:
    # Required: system USB serial port for radar (default: shown below)
    serial_port: /dev/ttyACM0

time:
    # Optional: Set a timezone to use in the UI (default: use browser local time)
    # timezone: America/Los_Angeles
    # Optional: For internet-connected deployments, sync using `timedatectl set-npt` (default: shown below)
    # Note: for offline deployments, time will stop whenever power is disconnected
    npt_set: True


</code></pre>

