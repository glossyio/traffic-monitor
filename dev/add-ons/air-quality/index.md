______________________________________________________________________

## description: Add the Enviro+ air quality sensor to a Traffic Monitor: hardware, the sensor software, and the settings that connect it.

# Air quality sensor

The optional air quality sensor measures gases, particulate matter, temperature, pressure, humidity, and light. Readings go into the device's database every five minutes and appear on the legacy dashboard.

We make no warranty on the accuracy of the sensor or its data. If you have an environmental science background, we'd welcome your [help](https://docs.trafficmonitor.ai/dev/development/contributing/index.md).

## Hardware

The Pimoroni [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/) board with the Plantower [PMS5003](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/) particulate matter sensor, connected to the Raspberry Pi's GPIO header with a [ribbon cable](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/recommended-hardware/#air-quality-sensor). The [assembly steps](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/assembly-instructions/#air-quality-sensor) show where the sensor sits in the enclosure. Pimoroni's [getting started guide](https://learn.pimoroni.com/article/getting-started-with-enviro-plus) covers the board itself.

## Sensor software

The sensor is read by [greendormer/enviroplus-monitor](https://github.com/greendormer/enviroplus-monitor), a Python service that runs on the Raspberry Pi and publishes readings to the device's MQTT broker. Install it following that repository's instructions, then set these keys in its `config.json` ([key reference](https://github.com/greendormer/enviroplus-monitor/blob/main/config_readme.md)):

| Key                               | Value                        | Why                                                                                                         |
| --------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `enable_send_data_to_homemanager` | `true`                       | Publish readings over MQTT                                                                                  |
| `mqtt_broker_name`                | `"localhost"`                | The Traffic Monitor's broker, on port 1883                                                                  |
| `indoor_outdoor_function`         | `"Outdoor"`                  | Use the outdoor topic                                                                                       |
| `outdoor_mqtt_topic`              | `"aq/sensorname01/readings"` | The topic must start with `aq/`, and the middle part is the sensor's name in the Traffic Monitor's settings |
| `enable_display`                  | `false`                      | The board's screen is inside the enclosure                                                                  |
| `long_update_delay`               | `300`                        | Seconds between readings                                                                                    |

Set the location keys for your site as well. The software uses them to calibrate the pressure and gas readings for altitude, and to work out sunrise and sunset:

```
{
    "altitude": 49,
    "city_name": "Portland",
    "time_zone": "America/Los_Angeles",
    "custom_locations": [
        "Portland, United States of America, America/Los_Angeles, 45.52, -122.681944"
    ]
}
```

## Turn the sensor on in the Traffic Monitor

In `/opt/traffic-monitor/node-red-tm/config/config.yml`, under `sensors: airquality_monitors:`, set the sensor's entry to `enabled: true`. The entry's name must match the middle part of the MQTT topic:

```
sensors:
    airquality_monitors:
        sensorname01:
            enabled: true
```

The change takes effect when you save the file. Readings from a sensor that isn't enabled are dropped.

## What to expect

- The first readings arrive after the sensor's stabilization period, five minutes by default (`startup_stabilisation_time` in `config.json`).
- The gas readings are reported as uncalibrated for the first 100 minutes, while the gas sensor warms up.
- Readings show in the **Air Quality** section of the legacy dashboard at `http://<device>/ui/`, and are stored in the `airquality` table. [Air quality](https://docs.trafficmonitor.ai/dev/data-and-payloads/air-quality-aq-payload/index.md) describes the payload and the columns.
- The Raspberry Pi and the AI accelerator give off heat. The enclosure separates the sensor from them, but temperature and humidity may still read high.
