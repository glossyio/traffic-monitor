---
description: Doppler radar payloads
---

# OPS243 Radar Payload

## Overview

### Hardware

The [OPS243-A](https://omnipresense.com/product/ops243-doppler-radar-sensor/) radar from [OmniPreSense](https://omnipresense.com/):&#x20;

> OmniPreSense’s OPS243 is complete short-range radar (SRR) solution providing motion detection, speed, direction, and range reporting. All radar signal processing is done on board and a simple API reports the processed data.

### Software

The OPS243 radar sensors include an easy-to-use [API interface](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) for returning a variety of radar readings and calculated values in JSON format. By default, we capture all of these values in separate tables:

* **DetectedObjectVelocity** (command `ON`). Sensor determines if an object is present by looking for 2 consecutive speed reports. If met, the max speed detected is reported. If a faster speed is detected, additional speeds are reported. This lowers the number of speed reports for a given detected object. Use On to turn the mode off.
* **TimedSpeedCounts** (command @O). Sensor counts and reports the cumulative number of objects (defined by DetectedObjectVelocity) that have gone by in a given period. Default TM setting is reporting every 300-seconds.
* **Raw Speed Magnitude** (command `OS`). Reports magnitude and associated speed of each reading. The magnitude is a measure of the size, distance, and reflectivity of the object detected. By default, TM captures the 3-burst speed/magnitude pairs and the single strongest magnitude and associated speed in separate tables for deep dive and easier analysis, respectively.
* **Vehicle Length** (command `OC`). From the docs: _Provides several parameters which can help identify the vehicle type and/or lane in which the vehicle is located_. This includes start/end time, frames, min/max MPH, magnitude, and length calculations.

## Database

\[insert attributes table here]

