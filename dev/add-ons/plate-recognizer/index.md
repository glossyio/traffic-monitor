# Plate Recognizer

Plate Recognizer is an optional add-on built on a commercial product from [Plate Recognizer](https://platerecognizer.com/), a company the Traffic Monitor project isn't affiliated with. It's off unless you install it. The add-on runs the company's on-device license plate reader in a container next to Frigate. For each `car` event from a camera you choose that passed through `zone_radar`, it reads the plate from Frigate's snapshot and stores the plate number, region, and vehicle make, model, and color.

Frigate has its own license plate recognition, which the Traffic Monitor doesn't turn on.

Danger

**Plates identify people.** With this add-on on, the database is no longer de-identified: the `plate_recognizer` table holds plate numbers. Keep the database on the device, don't share it, and make sure your use complies with local law. See [Data and privacy](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/index.md).

You need a Plate Recognizer account with an on-premise (SDK) license, which gives you an API token and a license key.

## Install

1. Run the installer with the add-on turned on:

   ```
   bash traffic-monitor/script/tmsetup.sh -C plate_recognizer
   ```

1. Put your credentials in `/opt/traffic-monitor/plate-recognizer/plate-recognizer.env`:

   | Variable      | Value                                         |
   | ------------- | --------------------------------------------- |
   | `TOKEN`       | Your Plate Recognizer API token               |
   | `LICENSE_KEY` | Your on-premise license key                   |
   | `WORKERS`     | Parallel readers. `2` suits a Raspberry Pi 5. |

1. Add the token and the add-on's address to `/opt/traffic-monitor/node-red-tm/config/config.yml`, and turn the add-on on for each camera whose events should be read:

   ```
   sensors:
       cameras:
           picam_h265:
               enabled: true
               plate_recognizer: true

   addons:
       plate_recognizer:
           token: <your API token>
           url: http://plate-recognizer:8080
   ```

1. Restart the add-on so it reads its env file, and again whenever you change that file:

   ```
   sudo systemctl restart plate-recognizer.service
   ```

   Node-RED picks up `config.yml` as soon as you save it, so it needs no restart.

Frigate's snapshots must stay on, which they are by default; the reader works from them.

## Data

Each read goes into the `plate_recognizer` table, keyed by the event it belongs to.

| Column                                                         | Type              | Meaning                                                                                               |
| -------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------- |
| `event_id`                                                     | TEXT, primary key | The `id` of the [event](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md) |
| `filename`                                                     | TEXT              | The snapshot that was read                                                                            |
| `timestamp`                                                    | TEXT              | The event's `frame_time`, when Frigate took the best frame of the car                                 |
| `camera_id`                                                    | TEXT              | Always `picam_h264`, whichever camera the event came from                                             |
| `processing_time`                                              | REAL              | Milliseconds the read took                                                                            |
| `plate_type`                                                   | TEXT              | Plate category, if the reader reports one                                                             |
| `plate_score`                                                  | REAL              | Confidence that a plate was found, 0 to 1                                                             |
| `plate_xmin`, `plate_ymin`, `plate_xmax`, `plate_ymax`         | INTEGER           | The plate's box in the snapshot, in pixels                                                            |
| `plate_value`                                                  | TEXT              | The plate number                                                                                      |
| `plate_value_score`                                            | REAL              | Confidence in the plate number, 0 to 1                                                                |
| `plate_region_value`                                           | TEXT              | The issuing region, such as `us-or`. The reader looks only for `us`, `us-or`, and `us-wa` plates.     |
| `plate_region_score`                                           | REAL              | Confidence in the region, 0 to 1                                                                      |
| `vehicle_type`                                                 | TEXT              | Vehicle category, such as `Sedan`                                                                     |
| `vehicle_score`                                                | REAL              | Confidence in the vehicle, 0 to 1                                                                     |
| `vehicle_xmin`, `vehicle_ymin`, `vehicle_xmax`, `vehicle_ymax` | INTEGER           | The vehicle's box in the snapshot, in pixels                                                          |
| `vehicle_make`, `vehicle_model`                                | TEXT              | Make and model                                                                                        |
| `vehicle_make_model_score`                                     | REAL              | Confidence in make and model, 0 to 1                                                                  |
| `vehicle_orientation`                                          | TEXT              | `Front`, `Rear`, or similar                                                                           |
| `vehicle_orientation_score`                                    | REAL              | Confidence in the orientation, 0 to 1                                                                 |
| `vehicle_color`                                                | TEXT              | Color                                                                                                 |
| `vehicle_color_score`                                          | REAL              | Confidence in the color, 0 to 1                                                                       |
| `json_payload`                                                 | TEXT              | The reader's full JSON response                                                                       |
