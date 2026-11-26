# config.yml settings

The Traffic Monitor's own settings live in `/opt/traffic-monitor/node-red-tm/config/config.yml` on the device. The installer writes it from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/config/config.yml.j2) on the first install and leaves it alone afterwards, unless you run the installer with `-f`.

The Traffic Monitor reads the file again whenever you save it, so changes take effect without a restart. If the file has a YAML error, it keeps the previous settings until the service restarts, and after a restart it has no settings at all until you fix the file.

Keep the three top-level sections (`thingsboard`, `deployment`, `sensors`) in the file. The file has no time settings: you set the device's time zone on the [Date and time](https://docs.trafficmonitor.ai/dev/use/device-health/#the-date-and-time-page) page, or with the installer's `-z` option, and an installer run without `-z` leaves it as it is. A `time` section left from an older install is ignored. The Default column below shows the values the template writes. A setting that's missing from the file behaves differently in a few cases:

- A camera or radar without `enabled` is off.
- A camera without `frigate_camera` is the Frigate camera with the same name as its entry.
- A radar without `opt_api_commands_array` gets no extra commands.
- ThingsBoard without `host` stays off.
- A device without a `sharing` section shares the rounded location only.
- A camera whose `camera_radar` names a radar that isn't in the file records its events without a radar, and Node-RED logs a warning. On a device without a radar, remove `camera_radar` or keep the radar's entry with `enabled: false`.

## thingsboard

Uploads events, readings, and device telemetry to a [ThingsBoard](https://thingsboard.io/) server. The control app's [Sharing page](https://docs.trafficmonitor.ai/dev/use/sharing/index.md) writes `enabled`, `host`, `protocol`, and `port`, so you rarely edit them here. See [MQTT and ThingsBoard](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/index.md).

| Setting    | Type              | Default                                                                | Meaning                                                                                                                          |
| ---------- | ----------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`  | `true` or `false` | `false`                                                                | Turn the upload on.                                                                                                              |
| `host`     | text              | `tb.roadwaybiome.com` (Traffic Monitor's server, set by the installer) | The server's hostname. If it starts with `http://` or `https://`, that is used and `protocol` is ignored. Required when enabled. |
| `protocol` | `http` or `https` | `https`                                                                | How to reach the server.                                                                                                         |
| `port`     | number            | none                                                                   | Set it only if the server isn't on the standard port for the protocol.                                                           |

The device's access token isn't in this file. Set it on the Sharing page's [Access token](https://docs.trafficmonitor.ai/dev/use/sharing/#set-the-access-token) section; it's kept with the device's other secrets.

## sharing

What the device shares, and for which server. The control app's [Sharing page](https://docs.trafficmonitor.ai/dev/use/sharing/index.md) writes this section when an administrator saves it, and Node-RED reads it. A choice made here by hand has no effect, so you never need to edit it.

| Setting          | Type                      | Meaning                                                                                                                                                                                                             |
| ---------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `target`         | `maintainer` or `own`     | Whether the choices were made for Traffic Monitor's server or for an operator's own.                                                                                                                                |
| `host`           | text                      | The server the choices were made for. They count only while `thingsboard.host` is the same server.                                                                                                                  |
| `exact_location` | `true` or `false`         | Whether the exact location is sent. Only the Sharing page turns it on; the device writes a `true` that someone set by hand back to `false`.                                                                         |
| `public_map`     | `none` or `rounded_point` | Whether the device is shown on the public map.                                                                                                                                                                      |
| `notice_version` | text                      | The version of the sharing notice the choice was made under. `own-server` for an operator's own server, where the notice doesn't apply, and `pre-consent` for an upload that was on before any choice was recorded. |

A missing `sharing` section means the device shares the rounded location only, with no exact location and no map. When the upload is on, the control app writes the section back with both turned off, even if they were chosen before the section went missing. The installer's `-f` leaves the section out, which turns every choice off; see [What the installer's `-f` does to sharing](https://docs.trafficmonitor.ai/dev/use/sharing/#what-the-installers-f-does-to-sharing).

## deployment

Where the device is. Every event and reading is stored with a deployment id that points at these values. The control app's [Location page](https://docs.trafficmonitor.ai/dev/use/location/index.md) writes them when you claim the device, deploy it to a place, change the precision, or correct a value, so you rarely edit them here. All of them are optional.

| Setting              | Type                                                  | Default | Meaning                                                                                                                                                                                                                                                                                                                       |
| -------------------- | ----------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `survey_id`          | `<8 lower-case hex digits>-si`, such as `3f9a1c2e-si` | empty   | The place in use, with no coordinates in it. The Location page writes it. Each device makes its own ids, and two devices never need to share one. Upper case is folded to lower case; an id in any other form is ignored and logged as an error.                                                                              |
| `database_precision` | `none`, `1`, or `2`                                   | `'2'`   | How many decimal places of `lat` and `lon` the database keeps: `none` stores no coordinates, `1` about 10 km, `2` about 1 km. A number without quotes works too.                                                                                                                                                              |
| `lat`                | decimal degrees, such as `45.52252`                   | empty   | Latitude of the place in use, optional, with five decimal places at most. The database stores it rounded to `database_precision`; this file and the control app keep the exact value.                                                                                                                                         |
| `lon`                | decimal degrees, such as `-122.69120`                 | empty   | Longitude, optional, with the same rules as `lat`. Set both or neither: a row with only one gets neither.                                                                                                                                                                                                                     |
| `timezone`           | a time zone name, such as `America/New_York`          | empty   | The place in use's time zone, recorded with its deployments whatever the precision, also when no location is stored. The control app writes it from the zone you set for the place, and puts it back when it differs, so a hand edit doesn't last. A value that isn't a name of this shape is ignored and logged as an error. |
| `heading_deg`        | a whole number from 0 to 359                          | empty   | The way the camera and radar face, in degrees clockwise from true north: 0 is north, 90 is east, 180 is south, and 270 is west. Optional; a value that isn't a whole number in that range is logged as an error.                                                                                                              |

A change of `survey_id`, or of a sensor's `heading_deg`, `pitch_deg`, `height_m`, `view_distance_m`, or `mount`, closes that sensor's current deployment and starts a new one. A change of `lat`, `lon`, or `timezone` doesn't: a new time zone is written onto the current deployment and the place's earlier ones. While `survey_id` is empty, current deployments stay as they are, and a change of any of the five waits until you set one. When you first set `survey_id`, a current deployment with no survey id, the same heading, and the same mounting takes it over and keeps its deployment id.

Lowering `database_precision` rewrites the current deployments in place. Raising it takes effect from the next new deployment, because coordinates already rounded can't be made finer. The Location page can also round the rows already stored; see [Choose the precision](https://docs.trafficmonitor.ai/dev/use/location/#choose-the-precision).

A `deployment:` block under a camera or radar can hold `heading_deg`, for a device whose cameras face different ways, and the four mounting settings below. A `lat` or `lon` there isn't read, because the location belongs to the whole device. The installer removes it, and the Status page's Location check warns about it until then.

### How a sensor is mounted

Beside its heading, each sensor can record how it is mounted. The four settings go under the sensor's own `deployment:` block, because they differ from one sensor to the next. A radar that sits with a camera can hold the same values. All of them are optional and empty by default.

| Setting           | Type                          | Meaning                                                                                                                                                                                                                          |
| ----------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pitch_deg`       | a number from 0 to 90         | How far below level the centre of the sensor's view points, in degrees, rounded to one decimal. 0 is level, and 90 is straight down.                                                                                             |
| `height_m`        | a number above 0, at most 100 | How high the sensor is above the road, in metres, rounded to two decimals.                                                                                                                                                       |
| `view_distance_m` | a number from 0 to 1,000      | How far along the ground the centre of the view is, in metres, rounded to two decimals.                                                                                                                                          |
| `mount`           | `tripod`, `pole`, or `window` | The usual mount the sensor was set up from. The file and the database accept any 1 to 32 lower-case letters, digits, and underscores. The control app saves one of the three, or the key the file already holds for that sensor. |

A number is rounded first, and the limit applies to the rounded value. A value outside its limit, or one that isn't a number, is ignored, and the Status page lists a config error that names the setting's path but not its value. `mount` is case-sensitive: `Pole` is an error. Tilt and distance describe the same thing from two sides: with the height and one of them, the other follows. The control app's [Mounting page](https://docs.trafficmonitor.ai/dev/use/location/#record-how-the-unit-is-mounted) writes whichever you measured and works out the other; you can also write the values by hand.

A hand edit of any of the five starts a new deployment, just as a change of heading does. The control app's own save asks first whether the unit moved or turned, and corrects the open deployment in place when it was only measured better; a hand edit has no such question. The control app only records the mounting of cameras and radars: an air quality monitor keeps its heading.

### If your file still says `bearing`

Before this release, the file held `bearing`, one of eight compass points (`n`, `ne`, `e`, `se`, `s`, `sw`, `w`, `nw`), in place of `heading_deg`. Node-RED converts it for you each time it starts, before it records anything: each `bearing` becomes `heading_deg`, written as the centre of its point.

| Old `bearing` | `heading_deg` |
| ------------- | ------------- |
| `n`           | 0             |
| `ne`          | 45            |
| `e`           | 90            |
| `se`          | 135           |
| `s`           | 180           |
| `sw`          | 225           |
| `w`           | 270           |
| `nw`          | 315           |

A `bearing` that is empty becomes an empty `heading_deg`. One that isn't one of the eight, such as `north`, is left in the file as it is, with a warning in the `node-red-tm.service` log that names the key but not its value. Write `heading_deg` in its place.

A `bearing` written into the file while Node-RED runs stays there until Node-RED next starts. Meanwhile Node-RED reads one of the eight points as its centre, so the device keeps recording, and any other value as no heading. The Status page's Location check warns about a `bearing` that holds a value, in the top-level `deployment` block and in the block of each sensor that is enabled. For one of the eight points it says to restart Node-RED, which converts it, and that if the warning is still there after the restart, the conversion failed and the `node-red-tm.service` log says why. For any other value, which Node-RED leaves, it says to write `heading_deg` and delete the `bearing`. An empty `bearing` isn't reported. Nothing writes `bearing` any more.

### Edit the location by hand

Use the [Location page](https://docs.trafficmonitor.ai/dev/use/location/index.md) to move the device or fix a value. If you edit this section by hand instead, Node-RED applies the change as soon as you save the file, and the control app records it the next time it's opened, on its home page, Status page, or Location page:

- **`survey_id` set to a place the page lists** is a move there. The file takes that place's location, replacing any `lat` or `lon` you changed in the same edit. Node-RED starts the new deployments as soon as you save, at the location the file held then, and the control app gives them the place's location when it records the move. If the place has no location, those deployments keep the one the file held. The sensors keep the mounting the file holds. The values last saved for that place aren't written; the control app offers them until someone saves them, as after **Deploy here**.
- **`survey_id` set to an id the page doesn't list** becomes a new place, in use, at this file's `lat` and `lon`.
- **Only `lat` or `lon` changed** is a correction of the place in use, as **Correct location** would be: the place's stored rows take the new location.
- **`survey_id` emptied**, as `tmsetup.sh -f` leaves it, is put back: the control app writes the place in use's id into the file again, and gives each sensor with an empty heading the way it faces at that place, together with how it was last recorded as mounted there. Only a mounting saved for this use goes back: values offered after a move that nobody has saved yet stay out. A sensor whose heading in the reset file is blank, or equal to the one stored for the place, gets its mounting back, unless the reset file already gives it one of the four mounting settings, and a sensor that gets everything back starts no new deployment. A different heading someone wrote stays, and so does a mounting setting; that sensor gets nothing back and starts a new deployment. `database_precision` goes back to the last value the control app saw while the file named a place, because after a reset the file holds the template's `'2'`. A coarser value you typed into the reset file stays. To choose a finer one, use the Location page, or edit the file once `survey_id` is back. If the place has a location, `lat` and `lon` get it back, whatever the file holds, because after a reset they come from the installer, not from you; correct a place's location on the Location page. If the place has none, a location in the file is a correction, as above. A typo stays as you typed it.
- **`timezone` changed or emptied** is put back to the zone the control app holds for the place in use, and the place's stored deployments get that zone too. Set a place's time zone in the control app instead. A file with no `timezone` key, at a place with no time zone, is left as it is.
- **`lat` and `lon` both emptied**, when the place in use has a location, are put back too, because a place's location can be corrected but not removed. To keep the location out of the database, choose **No location stored** as the [precision](https://docs.trafficmonitor.ai/dev/use/location/#choose-the-precision).
- **A `lat` or `lon` that isn't a number in range**, such as one with a typo, stays in the file as you typed it. New deployments store no location until you fix it, and the Status page's Location check names the key.

On a device upgraded from a release that recorded coordinates, the update leaves `survey_id` empty, and the control app fills it in the first time it's opened after Node-RED has started; see [Places after an update](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/update/#places-after-an-update).

## sensors.cameras

One entry per camera. The control app's [Cameras page](https://docs.trafficmonitor.ai/dev/use/cameras/index.md) edits them. The entry's name is the camera's name in the database and in everything the device shares. `frigate_camera` says which Frigate camera the entry is; without it, the entry's name is also the camera's name in Frigate. The default camera is `picam_h265`. Events from a Frigate camera that no entry points at, or from a disabled camera, aren't recorded. If two entries point at the same Frigate camera, the first one in the file is used and the other is logged as an error.

To rename a camera in Frigate, rename it in Frigate's config and choose **Save & Restart**. Frigate uses a new camera name only after it restarts, so **Save** alone changes nothing yet. Then open the control app's [Cameras page](https://docs.trafficmonitor.ai/dev/use/cameras/#after-renaming-a-camera-in-frigate) and point the camera's entry at the new name. The entry keeps its name, so the camera's data carries on under the same name. Until the entry points at the new name, that camera's events aren't recorded, and the Status page's **Cameras in config.yml** check shows an error.

| Setting            | Type                                | Default                   | Meaning                                                                                                                           |
| ------------------ | ----------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `frigate_camera`   | a camera name from Frigate's config | none                      | Frigate's name for this camera, when it differs from the entry's name. It stays on the device.                                    |
| `enabled`          | `true` or `false`                   | `true` for `picam_h265`   | Record this camera's events. Frigate keeps running either way.                                                                    |
| `camera_radar`     | a radar name from `sensors.radars`  | `TM_RADAR_SERIAL_PORT_00` | The radar that supplies speeds for this camera. One radar can serve several cameras. Leave it out on a device without a radar.    |
| `plate_recognizer` | `true` or `false`                   | `false`                   | Send this camera's events to the [Plate Recognizer](https://docs.trafficmonitor.ai/dev/add-ons/plate-recognizer/index.md) add-on. |
| `deployment`       | block                               | inherited                 | Per-camera `heading_deg`, and how it is [mounted](#how-a-sensor-is-mounted).                                                      |

## sensors.radars

One entry per radar. A radar's name is the name of the variable that holds its serial port in [node-red-tm.env](https://docs.trafficmonitor.ai/dev/configuration/environment/index.md), `TM_RADAR_SERIAL_PORT_00` through `TM_RADAR_SERIAL_PORT_03`.

| Setting                  | Type                     | Default                              | Meaning                                                                                                                                                                                                                                                                                                        |
| ------------------------ | ------------------------ | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`                | `true` or `false`        | `true` for `TM_RADAR_SERIAL_PORT_00` | Read this radar. Set it to `false` on a device without a radar.                                                                                                                                                                                                                                                |
| `opt_api_commands_array` | a JSON array in a string | `'["^/+0.00\n", "^/-0.00\n"]'`       | Extra [OPS243 API](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) commands sent to the radar when the service starts and whenever you save this file, after the Traffic Monitor's own setup commands. The default sets the cosine correction to 0 degrees in both directions. |
| `deployment`             | block                    | inherited                            | Per-radar `heading_deg`, and how it is [mounted](#how-a-sensor-is-mounted).                                                                                                                                                                                                                                    |

## sensors.airquality_monitors

One entry per [air quality sensor](https://docs.trafficmonitor.ai/dev/add-ons/air-quality/index.md), named as the middle part of the topic the sensor publishes to: `aq/<name>/readings`.

| Setting               | Type              | Default    | Meaning                                                                                 |
| --------------------- | ----------------- | ---------- | --------------------------------------------------------------------------------------- |
| `enabled`             | `true` or `false` | `false`    | Record this sensor's readings. Readings from a sensor that isn't enabled are dropped.   |
| `mqtt_topic_incoming` | text              | `readings` | Present in the template but not used. The device subscribes to every topic under `aq/`. |

## addons.plate_recognizer

Only needed with the [Plate Recognizer](https://docs.trafficmonitor.ai/dev/add-ons/plate-recognizer/index.md) add-on. The section isn't in the template; add it.

| Setting   | Type         | Default                | Meaning                                                                                                                                            |
| --------- | ------------ | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `url`     | URL          | none                   | The add-on's address inside the device, `http://plate-recognizer:8080`.                                                                            |
| `regions` | list of text | `us`, `us-or`, `us-wa` | The region codes Plate Recognizer may match plates to, for example `[gb]`. A value that isn't a list of text, or an empty list, means the default. |

The API token and license key aren't in this file. Set them on the control app's [Device page](https://docs.trafficmonitor.ai/dev/use/device-health/#tokens-and-keys); plates aren't read until they're set.
