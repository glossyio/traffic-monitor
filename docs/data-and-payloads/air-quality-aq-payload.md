---
description: The air quality sensor's MQTT payload and the airquality table, with the unit and meaning of each reading.
---

# Air quality

The optional [air quality sensor](../add-ons/air-quality.md) publishes a reading over MQTT every five minutes. The Traffic Monitor stores each reading as a row in the `airquality` table.

## MQTT payload

The sensor software publishes to `aq/<sensor>/readings`, where `<sensor>` is the sensor's name in [config.yml](../configuration/node-red-config.md#sensorsairquality_monitors). Readings are dropped unless that sensor is enabled there.

```json
{
    "gas_calibrated": false,
    "bar": [1009.44, "0"],
    "hum": [28.7, "2"],
    "pm025": 0,
    "pm10": 0,
    "pm01": 0,
    "dew": 2.1,
    "temp": 21,
    "temp_min": 20.9,
    "temp_max": 21.1,
    "gas_red": 4.2,
    "gas_oxi": 0.15,
    "gas_nh3": 0.69,
    "lux": 1.2,
    "proximity": 255,
    "lux_raw": 1.16185,
    "temp_raw": 28.68982029794099,
    "bar_raw": 1003.7122773175154,
    "hum_raw": 18.31337919009301,
    "gas_red_raw": 140805,
    "gas_oxi_raw": 103585,
    "gas_nh3_raw": 227871,
    "current_time": 1738698665.077546
}
```

`bar` and `hum` are pairs: the value, then a comfort-level code (`"0"` stable to `"4"` storm for pressure; `"1"` good, `"2"` dry, `"3"` wet for humidity). Only the value is stored. `temp_min`, `temp_max`, and the sensor software's `Forecast` object aren't stored. The sensor software's [README](https://github.com/greendormer/enviroplus-monitor) explains how it compensates and calibrates the readings.

## airquality table

| Column | Type | Meaning | Unit |
|---|---|---|---|
| `entryDateTime` | REAL | When the reading was taken (`current_time` in the payload) | Unix time in seconds |
| `gas_calibrated` | INTEGER | Whether the gas sensor had finished warming up, which takes about 100 minutes after the sensor software starts | `1` yes, `0` no |
| `temp` | REAL | Temperature, compensated for the heat of the device | °C |
| `bar` | REAL | Air pressure, compensated for altitude | hPa |
| `hum` | REAL | Relative humidity, compensated | % |
| `dew` | REAL | Dew point, calculated from temperature and humidity | °C |
| `temp_raw` | REAL | Temperature as measured | °C |
| `bar_raw` | REAL | Air pressure as measured | hPa |
| `hum_raw` | REAL | Relative humidity as measured | % |
| `pm01` | REAL | Particulate matter up to 1 µm | µg/m³ |
| `pm025` | REAL | Particulate matter up to 2.5 µm | µg/m³ |
| `pm10` | REAL | Particulate matter up to 10 µm | µg/m³ |
| `gas_red` | REAL | Reducing gases, such as carbon monoxide and hydrogen, compensated for drift | ppm |
| `gas_oxi` | REAL | Oxidizing gases, such as nitrogen dioxide and chlorine, compensated for drift | ppm |
| `gas_nh3` | REAL | Ammonia, compensated for drift | ppm |
| `gas_red_raw` | REAL | Reducing gas sensor resistance as measured | Ω |
| `gas_oxi_raw` | REAL | Oxidizing gas sensor resistance as measured | Ω |
| `gas_nh3_raw` | REAL | Ammonia sensor resistance as measured | Ω |
| `lux` | REAL | Light, with a proximity-adjusted minimum | lux |
| `lux_raw` | REAL | Light as measured | lux |
| `proximity` | REAL | Proximity sensor reading; high when something is close to the board | 0 to 255 |
| `sensorName` | TEXT | The sensor's name | |
| `deployment_id` | TEXT | The [deployment](data-overview.md#deployment) the reading was taken in | |

## The sensors on the board

| Reading | Sensor | Notes |
|---|---|---|
| Gases | [MiCS-6814](https://www.sgxsensortech.com/content/uploads/2015/02/1143_Datasheet-MiCS-6814-rev-8.pdf) | Measures resistance for reducing, oxidizing, and ammonia gases. The sensor software converts resistance to ppm, compensating for temperature, humidity, and pressure, and recalibrates daily for drift. Treat the ppm values as relative; see the discussion in [pimoroni/enviroplus-python #47](https://github.com/pimoroni/enviroplus-python/issues/47) and [#67](https://github.com/pimoroni/enviroplus-python/issues/67). |
| Temperature, pressure, humidity | [BME280](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf) | The Raspberry Pi and AI accelerator warm the enclosure, so the compensated values are the ones to use. Pressure updates every 20 minutes. |
| Light and proximity | [LTR-559](https://optoelectronics.liteon.com/upload/download/DS86-2013-0003/LTR-559ALS-01_DS_V1.pdf) | |
| Noise | [SPH0645 MEMS microphone](https://media.digikey.com/pdf/Data%20Sheets/Knowles%20Acoustics%20PDFs/SPH0645LM4H-B.pdf) | Not stored in the database |
| Particulate matter | Plantower [PMS5003](http://www.aqmd.gov/docs/default-source/aq-spec/resources-page/plantower-pms5003-manual_v2-3.pdf) | |
