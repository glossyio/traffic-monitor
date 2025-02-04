---
description: Enviro + Air Quality sensor from Pimoroni for environmental conditions
---

# Air Quality (AQ) Sensor Specifications

{% hint style="info" %}
The AQ software is available at [greendormer/enviroplus-monitor](https://github.com/greendormer/enviroplus-monitor). It is based on the wonderful work from the [roscoe81/enviro-monitor](https://github.com/roscoe81/enviro-monitor) and [Pimoroni Enviroplus](https://github.com/pimoroni/enviroplus-python) projects.
{% endhint %}

## Hardware

* [Enviro for Raspberry Pi](https://www.pishop.us/product/enviro-for-raspberry-pi/) – **Enviro + Air Quality**
  * Enviro for Raspberry Pi – **Enviro + Air Quality**
  * Air quality (pollutant gases and particulates\*), temperature, pressure, humidity, light, and noise
  * [Getting started](https://learn.pimoroni.com/article/getting-started-with-enviro-plus)
* [PMS5003 Particulate Matter Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/) for Enviro
  * Monitor air pollution cheaply and accurately with this matchbox-sized particulate matter (PM) sensor from Plantower!&#x20;
  * It senses particulates of various sizes (PM1, PM2.5, PM10) from sources like smoke, dust, pollen, metal and organic particles, and more.

## Software

The AQ software is available at [greendormer/enviroplus-monitor](https://github.com/greendormer/enviroplus-monitor) as a Python service script that communicates with the Traffic Monitor Node-RED flow via MQTT messages. See the repository for installation and setup instructions.

### config.json

See [Config Readme](https://github.com/greendormer/enviroplus-monitor/blob/main/config_readme.md) for a detailed description of every available key.

### Recommended config settings

{% hint style="info" %}
Note: At present, readings will be sent every 5-minutes and _this is hard-coded_. This will be parameterized in a future release.
{% endhint %}

The following are important keys for the recommended default Traffic Monitor -specific configuration:

* `"enable_send_data_to_homemanager": true` in order to send MQTT payloads to specified broker
* `"mqtt_broker_name": "localhost"` to send to Node-RED MQTT broker (assumes port 1883)
* `"indoor_outdoor_function": "Outdoor"` to utilize `outdoor_mqtt_topic`
* `"enable_display": false` since the AQ sensor will be in an enclosure
* `"outdoor_mqtt_topic": "aq/sensorname01/readings"` for sending messages, must start with "aq" and the middle element, "sensorname01" must be defined in your TM config
* `"long_update_delay": 300` for time between sending MQTT messages (default 300-seconds)

### Deployment-specific config settings

The following location-based settings need to be set per-deployment for your location. They are utilized by the [`astral` package](https://astral.readthedocs.io/en/latest/package.html) for calculating the times of various aspects of the sun and phases of the moon (lat/lon, time zone) and calibrating temperature, humidity, barometer, and gas (altitude) readings.

```json
{
    "altitude": 49,
    "city_name": "Portland",
    "time_zone": "America/Los_Angeles",
    "custom_locations": [
        "Portland, United States of America, America/Los_Angeles, 45.52, -122.681944"
    ]
}
```

# Air Quality MQTT Incoming Payload

The TM AQ application sends messages via MQTT integration on the `aq/readings` topic.

{% hint style="warning" %}
The sensor needs to stabilize (default 5-minutes) after the script initializes before it will send external updates (via MQTT). This is defined by `startup_stabilisation_time` in config.json.
{% endhint %}

```json
{
    "gas_calibrated": false,
    "Bar": [
        1013.93,
        "0"
    ],
    "Hum": [
        45.9,
        "1"
    ],
    "Forecast": {
        "Valid": false,
        "3 Hour Change": 0,
        "Forecast": "Insufficient Data"
    },
    "p025": 0,
    "p10": 0,
    "p01": 0,
    "Dew": 7.5,
    "Temp": 19.5,
    "Min Temp": 19.5,
    "Max Temp": 19.5,
    "Red": 4.43,
    "Oxi": 0.16,
    "NH3": 0.66,
    "Lux": 0
}
```

| Key | Valid Values | Units | Notes |
| -------------- | ------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| gas_calibrated | true/false | | Hard-coded value (10-min) `gas_sensors_warmup_time = 6000` or `startup_stabilisation_time` when `reset_gas_sensor_calibration = true`|
| bar | [REAL, TEXT] | hPa, Comfort-level `{"0": "Stable", "1": "Fair", "3": "Poorer/Windy/", "4": "Rain/Gale/Storm"}` | Air pressure, compensated for altitude and temp as `Bar / comp_factor` where `comp_factor = math.pow(1 - (0.0065 * altitude/(temp + 0.0065 * alt + 273.15)), -5.257)` |
| hum | [REAL, TEXT] | %, Comfort-level `{"good": "1", "dry": "2", "wet": "3"}`| Adjusted for compensation factor set in `config.json` |
| Forecast | {OBJECT} | `Valid`: true/false, `3 Hour Change` is millibars difference in barometer readings, `Forecast` is description calculated from barometer change | Calculated forecast based on sensor barometer changes|
| p01 | REAL | ug/m3 (microgram per meter cubed, µg/m³) | Particulate Matter 1 micrometers / microns (PM1, PM<sub>1</sub>), Read directly using the `pms5003.pm_ug_per_m3()` method from the particulate matter sensor. |
| p025 | REAL | ug/m3 (microgram per meter cubed, µg/m³) | Particulate Matter 2.5 micrometers / microns (PM2.5, PM<sub>2.5</sub>), read directly using the `pms5003.pm_ug_per_m3()` method from the particulate matter sensor. |
| p10 | REAL | ug/m3 (microgram per meter cubed, µg/m³) | Particulate Matter 10 micrometers / microns (PM10, PM<sub>10</sub>), Read directly using the `pms5003.pm_ug_per_m3()` method from the particulate matter sensor. |
| dew | REAL | C | Calculated from Temp and Hum as `(237.7 * (math.log(dew_hum/100)+17.271*dew_temp/(237.7+dew_temp))/(17.271 - math.log(dew_hum/100) - 17.271*dew_temp/(237.7 + dew_temp)))` | 
| temp | REAL |  C | Adjusted for compensation factor set in `config.json` | 
| Min Temp | REAL | C | Minimum temperature measured while sensor was running (only resets on restart) | 
| Max Temp | REAL | C | Maximum temperature measured while sensor was running (only resets on restart) | 
| gas_red | REAL | ppm | Red PPM calculated as `red_in_ppm = math.pow(10, -1.25 * math.log10(red_ratio) + 0.64)`. `red_ratio` is compensated gas value, see Software notes. | 
| gas_oxi | REAL | ppm | Oxi PPM calculated as `oxi_in_ppm = math.pow(10, math.log10(oxi_ratio) - 0.8129)`. `oxi_ratio` is compensated gas value, see Software notes. | 
| nh3 | REAL | ppm | NH3 PPM calculated as `nh3_in_ppm = math.pow(10, -1.8 * math.log10(nh3_ratio) - 0.163)`. `nh3_ratio` is compensated gas value, see Software notes. | 
| lux | REAL | lux | Read directly using the `ltr559.get_lux()` method from the light sensor. | 
| temp_raw | REAL | C | Read directly from sensor absent compensation. |
| bar_raw | REAL | C | Read directly from sensor absent compensation. |
| hum_raw | REAL | % | Read directly from sensor absent compensation. |
| gas_red_raw | REAL | Ohms | Read directly from sensor using `gas_data.reducing` method absent compensation. |
| gas_oxi_raw | REAL | Ohms | Read directly from sensor using `gas_data.oxidising` method absent compensation. |
| gas_nh3_raw | REAL | Ohms | Read directly from sensor using `gas_data.nh3` method absent compensation. |
| current_time | REAL | Unix time in Seconds | Created by script upon reading values. |

# Air Quality TM Database&#x20;

\[insert attributes table here]

# Notes on Air Quality readings

## Gas sensor

The [MICS6814](https://www.sgxsensortech.com/content/uploads/2015/02/1143_Datasheet-MiCS-6814-rev-8.pdf) analog gas sensor:  _The MiCS-6814 is a robust MEMS sensor for the detection of pollution from automobile exhausts and for agricultural/industrial odors._ &#x20;

The sensor includes the ability to detect reductive (RED), oxidative (OXI), and ammonia (NH3) gases. The raw gas readings are measured as Ohms of resistance for their respective gasses, but the software compensates for temperature, humidity, altitude, and drift to provide PPM (parts per million) equivalents.* 

*See Software notes and additional discussions on [pimoroni/enviroplus-python #47](https://github.com/pimoroni/enviroplus-python/issues/47) and [pimoroni/enviroplus-python #67](https://github.com/pimoroni/enviroplus-python/issues/67). 

**Software notes**

* Gas calibrates using Temp, Humidity, and Barometric Pressure readings.
* Gas Sensors (`Red`, `Oxi`, `NH3`) take 100-minutes to warm-up and readings to become available
* To compensate for gas sensor drift over time, the software calibrates gas sensors daily at time set by `gas_daily_r0_calibration_hour`, using average of daily readings over a week if not already done in the current day and if warm-up calibration is completed. This compensates for gas sensor drift over time&#x20;
* Raw gas readings will also have compensation factors applied, determined by [regression analysis](https://github.com/roscoe81/enviro-monitor/blob/master/Regression_Analysis/Northcliff_Enviro_Monitor_Regression_Analyser.py).

## Temperature, pressure, and humidity

The [BME280](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf) temperature, pressure, humidity sensor with I2S digital output.

### Software notes

* `Temp` (temperature) and `Hum` (humidity) have cubic polynomial compensation factors applied to raw readings
* `Min Temp`and `Max Temp`are calculated over the entire time the script is running
* `Bar`(Barometer) reading updates only every 20 minutes
  * Air pressure reading has an altitude compensation factor applied (defined in config.json)
*   `Dew`(Dew Point) is calculated from temperature and humidity using the following calculation:&#x20;

    ```python
    dewpoint = (237.7 * (math.log(dew_hum/100)+17.271*dew_temp/(237.7+dew_temp))/(17.271 - math.log(dew_hum/100) - 17.271*dew_temp/(237.7 + dew_temp)))
    ```

## Optical (light, proximity)

The [LTR-559](https://optoelectronics.liteon.com/upload/download/DS86-2013-0003/LTR-559ALS-01_DS_V1.pdf) light and proximity sensor

## Noise&#x20;

MEMS microphone ([datasheet](https://media.digikey.com/pdf/Data%20Sheets/Knowles%20Acoustics%20PDFs/SPH0645LM4H-B.pdf)).

## Particulate matter (PM) &#x20;

The Plantower [PMS5003](http://www.aqmd.gov/docs/default-source/aq-spec/resources-page/plantower-pms5003-manual_v2-3.pdf) Particulate Matter (PM) Sensor.

\




\
