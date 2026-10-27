---
description: Use Frigate's debug view, object filters, masks, and camera streams to detect more of what you want and less of what you don't.
---

# Tune object detection

[Frigate](https://frigate.video/) does the object detection. How well it works depends on the mounting height and angle, the camera, and the weather, so expect to adjust it for each site. The Traffic Monitor is not affiliated with the Frigate project.

The Traffic Monitor's [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2) is tuned for roadways seen from an oblique angle, with a side view of objects as they pass. Everything in it can be changed in Frigate's own UI, at **Settings > Configuration editor**. Frigate's [configuration reference](https://docs.frigate.video/configuration/) explains every setting.

## See what Frigate sees

Go to **Settings > Debug** to watch detections live with their scores, and the motion regions Frigate is checking. **Explore** lists past detections with their snapshots, which is the quickest way to find missed bikes or a tree that's being called a person.

<figure markdown="span">
  ![Frigate debug view showing detection boxes, labels, and scores over a street](../assets/images/Screenshot_20250307_143756.png)
  <figcaption>The debug view shows how detection is performing</figcaption>
</figure>

## Object filters

Frigate tracks `bicycle`, `person`, `car`, `bus`, `motorcycle`, and `dog` by default. Each object type has two scores in the `objects: filters:` section of the config:

* `min_score` is the score needed to start tracking an object.
* `threshold` is the average score an object needs, over the time it's tracked, to count as a real detection.

The defaults set `bicycle` low, so most kinds of bike are detected, and `motorcycle` high, so a large e-bike isn't called a motorcycle. If you see false positives for a type, raise its `threshold`; if you miss objects, lower it. Frigate's [object filters](https://docs.frigate.video/configuration/object_filters/#object-scores) page describes these and the size and shape filters.

## Masks

Go to **Settings > Camera configuration > Masks / Zones**.

* A **motion mask** stops motion in an area, such as swaying branches or a timestamp overlay, from triggering detection.
* An **object mask** ignores detections of one object type in an area, such as a parked car that's detected every time the light changes.

!!! warning

    Use masks sparingly. Over-masking makes objects harder to track. A motion mask isn't the tool for cutting false positives; adjust the object filters first.

Frigate's [masks](https://docs.frigate.video/configuration/masks) page has the details.

## Higher-resolution stream

The Pi camera is set up to produce two streams. Frigate uses `picam_h265_detect` at 1536×864 by default, which gives the best balance of detail and load. A second stream, `picam_h265_detect_hr`, runs at 2304×1296 for cases where objects are small in the frame.

To switch, change two things in the configuration editor under `cameras: picam_h265:`: the input `path` to `rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect_hr`, and `detect: width: 2304` with `height: 1296`. Frigate fills in the `{…}` values from `frigate.env`. Then redraw the [zones](../setup-guide.md#3-adjust-the-zones) for the new frame size. The higher resolution costs CPU and may lower the frame rate on a busy road.

## Recordings and snapshots

By default, Frigate keeps a cropped snapshot of each detection and a recording of each alert and detection for about an hour, so you can check what was detected. The `record:` and `snapshots:` sections control this: set `enabled: false` to keep nothing, or raise `retain: days` to keep more. [Data and privacy](../data-and-payloads/data-overview.md) describes what the device stores.

Frigate can also publish a cropped snapshot of each detected object on the device's [MQTT broker](../data-and-payloads/integrations.md#mqtt). The Traffic Monitor doesn't use these snapshots, so new installs turn them off with `mqtt: enabled: false` under `cameras: picam_h265:`. On an older install, add those lines in the configuration editor. Frigate keeps publishing the events the Traffic Monitor counts.

```yaml
cameras:
  picam_h265:
    mqtt:
      enabled: false
```

## Better models

[Frigate+](https://docs.frigate.video/plus/) offers paid models fine-tuned on your own snapshots, which can raise accuracy for a difficult site.
