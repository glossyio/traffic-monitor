---
description: Enviro + Air Quality sensor from Pimoroni for environmental conditions
---

# Air Quality (AQ) Payload

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
* `"outdoor_mqtt_topic": "aq-readings"` for monitored message topic

### Deployment-specific config settings

These need to be configured per-deployment for your location. They are utilized by the [`astral` package](https://astral.readthedocs.io/en/latest/package.html) for calculating the times of various aspects of the sun and phases of the moon.

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

## Sensor MQTT Incoming Payload

The TM AQ application sends messages via MQTT integration on the `aq/readings` topic.

{% hint style="warning" %}
The sensor needs to stabilize (default 5-minutes) after the script initializes before it will send external updates (via MQTT). This is defined by `startup_stabilisation_time` in config.json.
{% endhint %}

```json
{
    "Gas Calibrated": true,
    "Bar": [
        1014.07,
        "0"
    ],
    "Hum": [
        70.3,
        "1"
    ],
    "P2.5": 0,
    "P10": 0,
    "P1": 0,
    "Dew": 10.8,
    "Temp": 16.2,
    "Min Temp": 13.7,
    "Max Temp": 16.8,
    "Red": 6.7,
    "Oxi": 0.21,
    "NH3": 1.51,
    "Lux": 0
}
```

### Database&#x20;

\[insert attributes table here]

## Notes on readings

### Gas sensor

MICS6814 analog gas sensor ([datasheet](https://www.sgxsensortech.com/content/uploads/2015/02/1143_Datasheet-MiCS-6814-rev-8.pdf)):  _The MiCS-6814 is a robust MEMS sensor for the detection of pollution from automobile exhausts and for agricultural/industrial odors._ &#x20;

The sensor includes the ability to detect reductive (RED), oxidative (OXI), and ammonia (NH3) gases.

**Software notes**

* Gas calibrates using Temp, Humidity, and Barometric Pressure readings.
* Gas Sensors (`Red`, `Oxi`, `NH3`) take 100-minutes to warm-up and readings to become available
* To compensate for gas sensor drift over time, the software calibrates gas sensors daily at time set by `gas_daily_r0_calibration_hour`, using average of daily readings over a week if not already done in the current day and if warm-up calibration is completed.&#x20;
* Raw gas readings will also have compensation factors applied, determined by [regression analysis](https://github.com/roscoe81/enviro-monitor/blob/master/Regression_Analysis/Northcliff_Enviro_Monitor_Regression_Analyser.py).

### Temperature, pressure, and humidity

BME280 temperature, pressure, humidity sensor ([datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)) with I2S digital output.

#### Software notes

* `Temp` (temperature) and `Hum` (humidity) have cubic polynomial compensation factors applied to raw readings
* `Min Temp`and `Max Temp`are calculated over the entire time the script is running
* `Bar`(Barometer) reading updates only every 20 minutes
  * Air pressure reading has an altitude compensation factor applied (defined in config.json)
*   `Dew`(Dew Point) is calculated from temperature and humidity using the following calculation:&#x20;

    ```python
    dewpoint = (237.7 * (math.log(dew_hum/100)+17.271*dew_temp/(237.7+dew_temp))/(17.271 - math.log(dew_hum/100) - 17.271*dew_temp/(237.7 + dew_temp)))
    ```

### Noise&#x20;

MEMS microphone ([datasheet](https://media.digikey.com/pdf/Data%20Sheets/Knowles%20Acoustics%20PDFs/SPH0645LM4H-B.pdf)).

### Particulate matter (PM) sensor&#x20;

Plantower PMS5003 Particulate Matter (PM) Sensor ([datasheet](http://www.aqmd.gov/docs/default-source/aq-spec/resources-page/plantower-pms5003-manual_v2-3.pdf)).

\




\
