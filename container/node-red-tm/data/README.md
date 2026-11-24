traffic-monitor
==============

Traffic monitoring solution node-red flow

### About

Traffic Monitor built with edge ML for object detection and radar for speed monitoring. Learn more at www.trafficmonitor.ai

### upload-lists.json

What the ThingsBoard upload may send. `settings.js` reads it when Node-RED starts and puts it in the global context as `upload_lists`, and the "upload gate" function on the `thingsboard` tab sends only what it lists:

- `telemetry`: the kinds of telemetry, such as `event` and `radar`.
- `attributes`: the client attributes.
- `event`: the fields of an event. A field that isn't listed is saved on the device and left out of the upload.
- `deployment`: the fields of a deployment row, in the telemetry's two lists and in each sensor's entry of the `deployments` attribute, which includes how the sensor is mounted (`heading_deg`, `pitch_deg`, `height_m`, `view_distance_m`, `mount`). A field that isn't listed is left out of the upload. `test_every_deployment_row_key_is_on_the_upload_list` checks that every key the engine's rows and the attribute's template write is on it.
- `watch_camera` and `watch_radar`: the fields of the watch log's camera and radar rows, which go out as the telemetry kind `watch`. `test_watch_fields_agree` checks each list against the table's columns and the INSERT that writes it.

Keep one name per line, so that two changes that each add a name don't conflict. When the file is missing or isn't JSON, `upload_lists` is `null` and the gate sends nothing. The installer copies the file on every run and restarts Node-RED when it changes. The gate sends nothing when any of the six lists is missing. A new event column goes in this list, or in `KEPT_ON_THE_UNIT` in `script/tests/test_node_red_flows.py` when it stays on the device; `test_event_fields_agree` checks the list against the flows and the schema.
