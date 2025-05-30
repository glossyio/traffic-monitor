---
description: Object detection event payload
---

# Events Payload

## Overview

Traffic Monitor object detection events are generated by the connected sensors by performing [object detection](https://en.wikipedia.org/wiki/Object_detection) to identify instances of roadway users such as cars, bikes, pedestrians, and more. Additional data and metadata may also be added via other sensors and processes to create an event payload.

### Hardware and Software

**The camera** is the primary detection method, powered by [Frigate NVR](https://frigate.video/). Events are created by optical camera observation and machine learning-powered [object detectors](https://docs.frigate.video/configuration/object_detectors) inference the frames to label [available objects](https://docs.frigate.video/configuration/objects).

_Future feature_: **The radar** may also generate object detection events. This is particularly useful for nighttime and low-light conditions or even deployments that do not utilize a camera. See [radar-payload.md](radar-payload.md "mention") for more information on radar readings.

## Frigate MQTT Incoming Payload

Events are recorded via the [Frigate MQTT](https://docs.frigate.video/integrations/mqtt) integration on the `frigate/events` topic containing `type: "end",`which indicates a complete capture event. See Frigate documentation for a full list of available attributes.

## Events Database

The following attributes are captured, by default, into `tmdb.events.sqlite`:

<table><thead><tr><th width="137">Attribute</th><th>Description</th><th width="113">SQLite data type</th><th>Valid values</th></tr></thead><tbody><tr><td>id</td><td>UUID for object detection. Will be generated by `source`<br>Frigate-generated from MQTT event `end`.<br>Radar-generated from flow.</td><td>TEXT, PRIMARY KEY</td><td>Frigate: Unix timestamp in seconds concatenated to a hyphen and randomly-generated 6-alphanumeric value; e.g. "1721144705.617111-fg3luy"<br>Radar: Unix timestamp in seconds concatenated to a hyphen and randomly-generated 8-alphanumeric value concatenated with a hypen r '-r'; e.g. "1721144705.617111-fg3luy4x-r"</td></tr><tr><td>camera</td><td>Name of camera for object detection (defined in Frigate config).<br>Frigate-generated from MQTT event `end`.</td><td>TEXT</td><td>Free-text</td></tr><tr><td>label</td><td>Object label assigned by Frigate.<br>Frigate-generated from MQTT event `end`.</td><td>TEXT</td><td>Assigned by model, based on <a href="https://docs.frigate.video/configuration/objects">Frigate available objects</a></td></tr><tr><td>sub_label</td><td>Additional informatoin assigned to Frigate event.<br>Frigate-generated from MQTT event `end`.</td><td>TEXT</td><td>Assigned via Frigate HTTP API</td></tr><tr><td>top_score</td><td>Model inference score for object label. This is the highest score as object moved through field of view.<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>0-1 value</td></tr><tr><td>frame_time</td><td>Unix timestamp in seconds for when the object was optimally identified by Frigate for the field of view.<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>Unix timestamp in Seconds</td></tr><tr><td>start_time</td><td>Unix timestamp in seconds for when the object first entered the field of view.<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>Unix timestamp in Seconds</td></tr><tr><td>end_time</td><td>Unix timestamp in seconds for when the object exited the field of view.<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>Unix timestamp in Seconds</td></tr><tr><td>entered_zones</td><td>JSON array list of zones in order the object entered each zone. Specified zones are used for various calculations.<br>Frigate-generated from MQTT event `end`.</td><td>TEXT</td><td>Free-text via Frigate; expected:<br>- "zone_capture" - region for counting objects<br>- "zone_radar" - radar detection field of view (FOV)<br>- "zone_near" - area closest to radar, for determining visual direction<br>- "zone_far" - area furthest from radar, for determining visual direction</td></tr><tr><td>score</td><td>Model inference score for the object to initiate tracking. Computed score as object moves through field of view.<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>0-1 value</td></tr><tr><td>area</td><td>Width*height of the bounding box for the detected object<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>0-24000000</td></tr><tr><td>ratio</td><td>Width/height of the bounding box for the detected object; e.g. 0.5 is tall (twice as high as wide box)<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>0-24000000</td></tr><tr><td>motionless_count</td><td>Number of frames the object has been motionless<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>Integer count; e.g. 0</td></tr><tr><td>position_changes</td><td>Number of times the object has changed position<br>Frigate-generated from MQTT event `end`.</td><td>REAL</td><td>Integer count; e.g. 2</td></tr><tr><td>attributes</td><td>Attributes with top score that have been identified on the object at any point<br>Frigate-generated from MQTT event `end`.</td><td>TEXT, JSON</td><td>JSON object with key:value pairs; e.g. {"face": 0.86}</td></tr><tr><td>direction_calc</td><td>Assigned object moving direction relative to device placement; i.e. "outbound" is moving away from device.</td><td>TEXT</td><td>"outbound" or "inbound"</td></tr><tr><td>speed_calc</td><td>Assigned speed/velocity calculated for entire time object was in the camera's field of view.</td><td>REAL</td><td>Positive, Negative corresponding to inbound and outbound direction, respectively</td></tr><tr><td>provenance</td><td>Source(s) of event detection. List any sensor on the device that captured or created this event. The first item in the array is considered the primary source.</td><td>TEXT, JSON</td><td>JSON Array with every sensor that confirms the same event. e.g. Camera sensor: frigate, Radar sensor: radar</td></tr><tr><td>radarName</td><td>Radar sensor name that is associated (via config) with the camera during the event, regardless if event was confirmed by radar (see provenance).</td><td>TEXT</td><td>Free-text, defined from configs</td></tr><tr><td>deployment_id</td><td>Each ID represents a unique deployment configuration and/or location for the device. This acts a foreign key link to the `deployment` table, `id` column.</td><td>TEXT, FOREIGN KEY</td><td>`deployment`.`id` foreign key, may be null</td></tr></tbody></table>

## Telemetry

### HTTP Telemetry

[ThingsBoard HTTP upload telemetry API](https://thingsboard.io/docs/reference/http-api/#telemetry-upload-api) requests are sent for each event as a single JSON payload containing:

* `ts: frame_time * 1000` - to make it milliseconds
* `values: {event:values}`- contains all attributes in [#events-database](events-payload.md#events-database "mention")

### MQTT Publications

The primary event are available on-device for downstream subscriptions (e.g. Home Assistant):

* **Topic**:  `tm/event`&#x20;
* **Payload**: Same as the [#events-database](events-payload.md#events-database "mention")

Additionally, there is a daily cumulative object count utilized for the on-device dashboard and connected displays:

* **Topic**: `tm/events`
* **Payload**: Daily cumulative counts of detected objects (resets at 0400 local time). Note, these can be adjusted in the Frigate config for [Available Objects](https://docs.frigate.video/configuration/objects).&#x20;
  * `car`
  * `person`
  * `bicycle`
  * `motorcycle`
  * `bicycle_adj` - bicycle plus motorcycle - adjust for eBikes, but this is addressed now by Frigate configs for each object and is unnecessary for most deployments
  * `person_adj` - person minus bicycle - Essentially represents "pedestrian count" since every bicycle will have \[at least one] rider that is detected independently of the bike.&#x20;
    * Scooters and other transit modes will likely only count as a person using the base model.&#x20;
    * Cars never have a person identified inside of them with the base model.
  * `dog`
  * `cat`
