---
description: Use Frigate's debug view, object filters, masks, and camera streams to detect more of what you want and less of what you don't, and use a Frigate+ model.
---

# Tune object detection

[Frigate](https://frigate.video/) does the object detection. How well it works depends on the mounting height and angle, the camera, and the weather, so expect to adjust it for each site. The Traffic Monitor is not affiliated with the Frigate project.

The Traffic Monitor's [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2) is tuned for roadways seen from an oblique angle, with a side view of objects as they pass. Everything in it can be changed in Frigate's own UI, at **Settings > Configuration editor**, when you're logged in to the device as the administrator. Frigate's [configuration reference](https://docs.frigate.video/configuration/) explains every setting.

Frigate's own login is off. The device's [login](../use/control-app.md) passes your username and role on to Frigate: the administrator gets Frigate's admin role, and viewers its viewer role, which can watch and review but not change settings. Frigate's **Logout** logs you out of the device. Keep `auth: enabled: false` and the `proxy:` section as they are; with Frigate's login on, Frigate asks for a second login of its own, separate from the device's accounts.

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

[Frigate+](https://docs.frigate.video/plus/) is a paid service from the Frigate project, separate from the Traffic Monitor. You submit snapshots from your device, label them on the Frigate+ website, and Frigate+ trains a model on them, which can raise accuracy for a difficult site. Its documentation covers the account, labeling, and training.

### Enter the key

Frigate+ gives your account an API key. Enter it on the control app's Device page, under [Tokens and keys](../use/device-health.md#tokens-and-keys). A key is 36 characters, a colon, and 40 lowercase letters or digits, as Frigate+ shows it; the page refuses anything else, so a mis-pasted key is caught there. Saving or removing the key restarts Frigate, which takes about a minute. Traffic isn't counted until it's back.

### Submit snapshots

The key is all Frigate needs to submit snapshots. Open **Explore** in Frigate, select a detection, and submit its snapshot to Frigate+. The default config keeps snapshots on, but only for about an hour (see [Recordings and snapshots](#recordings-and-snapshots)), so submit them soon or keep them longer.

A snapshot you submit leaves the device: Frigate sends it to Frigate+, and it can show people.

### Use a model

A model trained by Frigate+ has to be built for the device's detector:

| Device | Detector type to choose in Frigate+ |
|---|---|
| Coral accelerator | `edgetpu` |
| Hailo accelerator | `hailo8l` |
| No accelerator | `cpu` |

Choose the `yolov9` model type; `mobiledet` is the older one. The [Status page](../use/device-health.md#the-status-page) tells you which detector the device has, in its Hardware group.

To use a model on a device that's online, either:

* pick it in Frigate's **Settings > System > Detectors and model**, or
* in **Settings > Configuration editor**, replace the whole `model:` section with only the model's path, then choose **Save & Restart**:

    ```yaml
    model:
      path: plus://<model id>
    ```

    Remove every other key under `model:`; Frigate+ supplies them.

When Frigate restarts, it downloads the model and loads it. The model then appears on the device as two files in `/opt/traffic-monitor/frigate/config/model_cache/`, named after the model id: `<model id>` and `<model id>.json`.

### A device without internet

Frigate downloads a model only when one of its two files is missing, so a device that's offline can use a Frigate+ model too:

1. On another computer, download the model from Frigate+. You get two files: `<model id>` and `<model id>.json`.
2. Copy both to the device over SSH, into Frigate's model folder:

    ```bash
    scp <model id> <model id>.json <username>@<hostname>.local:
    ssh <username>@<hostname>.local
    sudo cp <model id> <model id>.json /opt/traffic-monitor/frigate/config/model_cache/
    ```

3. Set `path: plus://<model id>` in the configuration editor, as in [Use a model](#use-a-model), and choose **Save & Restart**.

Frigate loads the model from those files without contacting Frigate+. The key is then needed only to submit snapshots, which takes internet as well.

### A model of your own

You can also run a model that doesn't come from Frigate+. Copy its file into `/opt/traffic-monitor/frigate/config/model_cache/` as above, and set `path: /config/model_cache/<file>` in the `model:` section. Unlike a `plus://` model, it also needs the keys that describe it: `width`, `height`, `input_tensor`, `input_pixel_format`, `input_dtype`, `model_type`, and `labelmap_path`. Frigate's [reference config](https://docs.frigate.video/configuration/advanced/reference) lists their values. The model must suit the device's detector, as a Frigate+ model must.

### What the installer keeps

Running the installer with `-f` replaces Frigate's config with a fresh copy, but keeps the `model:` section you chose, however you set it, as long as it isn't the installer's own model. Comments inside the section are lost. After you change the accelerator, a kept model may not suit the new one, and the Status page says so. [What `-f` replaces](../reference/tmsetup.md#what-f-replaces) and [Add an accelerator later](../reference/tmsetup.md#add-an-accelerator-later) have the details.

### The Frigate+ check

The Status page's Configuration group has a **Frigate+** check. It compares the key with the `model:` section of Frigate's config and says whether Frigate could use the model:

| Status | Meaning |
|---|---|
| Passed | Frigate+ isn't in use: no key and no Frigate+ model. Or Frigate runs the Frigate+ model the config names. Without a key, it runs from the files on the device, and you can't submit snapshots. |
| Warning | A key is set, but Frigate runs the installer's model, its own default model (on a device with no `model:` section), or one of your own. Snapshots can be submitted. Once Frigate+ has trained a model, set it as in [Use a model](#use-a-model). |
| Problem | Frigate can't use the Frigate+ model the config names. Either no key is set and the model's files aren't on the device, so Frigate can't download it (**Set the key** opens Tokens and keys), or the model isn't built for the device's detector; where Frigate's log says why, the check quotes it. Also a problem: Frigate isn't running and its log ends with an error, which can mean it couldn't download the model (the check quotes that line), or the model id has characters an id can't have. |
| Couldn't run | Frigate's config is missing or isn't valid YAML, or Frigate isn't answering. Or Frigate is in safe mode for a reason other than the model, so whether it can use the model is unknown; the Apps group's **Frigate** check says why. |

When Frigate can't use its config, for example because of a model built for another detector, it starts in safe mode: it answers and looks healthy, but has no cameras and counts nothing. The Apps group's **Frigate** check reports that as a problem, whatever the cause, and quotes Frigate's messages. Fix the config in Frigate's configuration editor, then choose **Save & Restart**.
