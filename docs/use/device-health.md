---
description: Use the control app's Status, Device, and Date and time pages to see whether a Traffic Monitor works, restart what stopped, download diagnostics, reboot, and set the clock.
---

# Check and fix the device

Three pages in the [control app](control-app.md)'s menu tell you whether the device works and let the administrator fix the common problems from a phone, without SSH. A fourth, [Detection](detection.md), shows the object detection model and changes it:

* **Status** checks the services, apps, settings, hardware, and clock, and offers a fix for what's wrong.
* **Device** shows the device's facts and software versions, and has the diagnostics download, reboot, and shut down.
* **Date and time** compares the device's clock with your phone's or computer's and sets it.

The [home page](home-page.md) shows the Status page's summary under the device's name, such as **Everything is working**. Tap it to open the Status page.

## The Status page

The page opens with one sentence about the whole device:

| Summary | Meaning |
|---|---|
| Everything is working | Every check passed. |
| Working, with 2 things to look at | Some checks have a warning, and none has a problem. |
| 2 problems need attention | At least one check has a problem. |
| Some checks couldn't run | Some checks couldn't get an answer, and none found a warning or a problem. |

Below it, each check shows a mark, its name, and one or two sentences about what it found and what to do. A tick means it passed, a triangle a warning, a cross a problem, and a question mark that the check couldn't run. The page checks again every 10 seconds while it's open. **Refresh** checks at once.

The checks come in groups:

| Group | What it checks |
|---|---|
| Services | Each Traffic Monitor service: running, stopped, starting, or running after restarts that followed failures. Frigate restarts itself when you save its config; that doesn't count as a failure. When it restarts itself again and again within minutes, as when its AI accelerator has failed, that does count, and the row says so. |
| Apps | Frigate answers, isn't in safe mode (with no cameras because of a config error), and gets frames from each camera. When Frigate stopped on an error, the Frigate check quotes it. When Frigate isn't answering because it keeps stopping itself, the check says so and points at the Hardware group and the diagnostics. Node-RED answers, loaded `config.yml` without errors, and has its database at the version this install expects. The camera streams run, and Frigate reads them. The MQTT broker requires its login while port 1883 is open to the network. |
| Configuration | Frigate and `config.yml` agree on the names that link them: each Frigate camera has an entry under `sensors.cameras` that is enabled (see [The camera checks](#the-camera-checks)), it has the zones `zone_capture`, `zone_near`, `zone_far`, and `zone_radar`, each radar under `sensors.radars` is named after one of the `TM_RADAR_SERIAL_PORT_` variables in `node-red-tm.env`, and each camera's radar is enabled. The Location check is a problem when a `deployment` value in `config.yml` is one Node-RED won't accept, such as a coordinate out of range or a bearing with spaces around it, and names the key. It warns when a sensor still has its own `lat` or `lon`, when the device's places haven't been set up since an update, which the control app does by itself once Node-RED answers, and when `survey_id` names a place the device doesn't have, and links to the [Location page](location.md). In safe mode Frigate has no cameras, so the checks that read them, here and in the Apps group, report that they couldn't run and point at the Frigate check. It also checks the ThingsBoard upload: its settings, and that a token is set when the upload is on. The Frigate+ check says whether a Frigate+ key and a Frigate+ model are set together, and whether Frigate can use the model; see [The Frigate+ check](../configuration/frigate-config.md#the-frigate-check). See [config.yml settings](../configuration/node-red-config.md) and [First-time setup](../setup-guide.md). |
| Hardware | Each AI accelerator, from plugged in to passed to Frigate and listed in its config, or a warning when there's none and Frigate detects on the CPU. Whether detection works is Frigate's to report: when its detector keeps failing, Frigate restarts itself, and the Services and Apps rows say so. The video decoder Frigate uses for the camera. Each radar, from plugged in to read by Node-RED. |
| Device | Free storage (a warning under 2 GB, a problem under 512 MB), free memory (a warning under 200 MB), the processor's temperature (a warning from 80 °C, a problem from 85 °C), and the power supply: whether the Pi ran short of power or slowed itself down since it started. |
| Date and time | Whether the clock was ever set, and whether it keeps time from the internet. |

### Fix a problem

A check that isn't passing offers one of these:

* **A Restart button**, such as **Restart Frigate**, for a service that stopped or keeps failing. The device asks first and says what you'll notice, for example that traffic isn't counted while Frigate restarts. A note under the button says when the restart is under way.
* **Re-scan hardware**, at the end of the Hardware group while one of its checks isn't passing. It runs every check again at once, so you don't wait for the next check after you plug a device back in or follow the check's advice.
* **A link** to the page that fixes it, such as **Set the date and time**, **Diagnostics** on the Device page, or **Set the token** for the ThingsBoard upload, which opens [Tokens and keys](#tokens-and-keys), or **Set the key** for Frigate+, which opens the Frigate+ API key section of the [Detection page](detection.md#frigate-plus), or **Open the Location page** for the Location check, or **Open the Cameras page** (see [Cameras](cameras.md)) for the camera, zone, and radar-pairing checks.
* **A sentence** with the next step, such as rerunning the installer for Node-RED (`tmsetup.sh -t node-red-tm`; see [Installer options](../reference/tmsetup.md)).

### The camera checks

The **Cameras in config.yml** check compares Frigate's cameras with the entries under `sensors.cameras` in `config.yml`. An entry points at the Frigate camera named by its `frigate_camera` setting, or, when it has none, at the camera with the same name as the entry. The control app's [Cameras page](cameras.md) keeps the two in step; each problem below links to it.

| Result | Meaning |
|---|---|
| Problem | A camera that is on in Frigate has no entry pointing at it, so its events aren't recorded. Or two entries point at the same Frigate camera, and only the first is used. |
| Warning | An entry is enabled, but Frigate doesn't have that camera, or has it turned off. Or an entry's recording is off while its camera is on in Frigate, which is fine if you turned it off on purpose. |
| Passed | Every camera that is on in Frigate has an enabled entry. |
| Couldn't run | Frigate isn't answering or is in safe mode, so it has no cameras to compare, or `config.yml` can't be read. |

The check names an entry by its name in `config.yml` and, when that differs, Frigate's name for the camera in brackets. The **Zones** check looks at the same pairs: it warns when a camera that is on in Frigate and enabled in `config.yml` lacks one of the zones the flows expect. The **Radar names** check warns when a camera is paired with a radar that is missing from `sensors.radars` or turned off. The camera is still recorded, but it gets no speed or direction from a radar. A radar named differently from the `node-red-tm.env` variables is a problem, and has no link, because you fix that name in `config.yml`.

The control app can't restart itself. If it stops, see [If the control app is down](control-app.md#if-the-control-app-is-down).

## The Device page

The card at the top shows the device's name, its Raspberry Pi model and memory, the Traffic Monitor version, the serial number, how long it has been running, its free storage, the processor's temperature, and the power supply's state. **Software** lists the versions of Frigate, Node-RED, go2rtc, nginx, and the Hailo driver if installed, the Traffic Monitor commit, the operating system, and the kernel.

### Tokens and keys

Administrators set the credentials the device uses for outside services in **Tokens and keys**. The section is closed when the page opens; select its heading to open it. The Status page's **Set the token** link opens it for you. It lists the ThingsBoard access token, and the Plate Recognizer API token and license key when the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on is installed. Each is kept with the device's other secrets, not in `config.yml`. The [Frigate+](../configuration/frigate-config.md#better-models) API key is on the [Detection page](detection.md#frigate-plus), next to the models it fetches.

* A value is never shown back. The page says whether it's set and, for a token or key of 12 or more characters, its last four characters, so you can tell which one you entered. It never shows any of the license key.
* **Save** stores what you typed in the box. The eye icon shows it while you type. A ThingsBoard token takes letters, digits, and `. _ ~ -`. A Plate Recognizer value takes printable ASCII characters without spaces. Both are up to 256 characters long.
* **Remove** asks first, then empties the value. Without a ThingsBoard token the upload stops, and without the Plate Recognizer values plates aren't read.
* Saving or removing restarts the app that uses the value, and the page waits for it. The ThingsBoard token and the license key restart one app and take about thirty seconds. The Plate Recognizer API token restarts the add-on and Node-RED, which takes about a minute. Traffic isn't counted while Node-RED restarts.

An older device may have kept a token in `config.yml` or in the add-on's env file, or a Frigate+ key in `frigate.env`. The installer moves it to the device's secrets, so uploads, plate reads, and Frigate+ keep working, and the Device page and the Detection page show it as set. A warning on the Status page's ThingsBoard upload check says when `config.yml` still holds a token key, which nothing reads, or when the upload is on without a token.

### Download diagnostics

When you ask for help, send the diagnostics with your question. It's a text file with the device's facts, its date and time settings, every status check, the services' states, what the installer installed and found, and the last 50 lines of each service's log. Passwords, keys, tokens, and the setup code are replaced with `<redacted>`. So are the names Frigate uses for cameras whenever they differ from the camera's name in `config.yml`, because the name in `config.yml` is the one the device records and shares, and Frigate's own name stays on the device. The file names the device and holds its serial number.

* **Download diagnostics** saves the file.
* **Copy** puts the text on the clipboard, ready to paste into a message. If the browser doesn't allow it, the page shows the text in a box, already selected, for you to copy.

The camera names replaced are Frigate's cameras that have a different name in `config.yml`, Frigate's cameras that no entry in `config.yml` points at (read from Frigate and from Frigate's own configuration file, so they are covered while Frigate isn't running), and the names found in the copies of `config.yml` that the control app saves beside it. It saves one each time it changes `config.yml`, from the [Cameras page](cameras.md) or the [Location page](location.md), and keeps the last ten. A short name is replaced only when it stands alone as a word, so `front` is replaced in "front camera" but not in "frontage". Four limits:

* If you renamed a camera by editing `config.yml` by hand, there is no saved copy with the old name. The old name can then appear in log lines from before the change, until they scroll out of the logs.
* A short, everyday name such as `front` is replaced wherever that word appears in the file. That errs on the side of hiding too much.
* On a device whose `config.yml` still names a camera by the name you gave it in Frigate, that name is the one the device records, so it isn't replaced. [Switch the camera to a neutral name](cameras.md#use-a-neutral-name) first.
* When Frigate isn't answering and its configuration file can't be read (a YAML mistake in it, for example), a camera that has no entry in `config.yml` yet can't be recognized, so its name can appear in the log lines.

### Reboot or shut down

**Reboot the device** and **Shut down the device** each ask before they act. A reboot takes about two minutes, during which no page answers. If something such as a system update is holding the device up, or the control app isn't allowed to, the device says it can't reboot or shut down right now. Try again in a few minutes, and if it keeps happening, download the diagnostics.

!!! warning "Shut down only when you can reach the device"

    After a shutdown, nothing starts the device again from the network. To turn it back on, unplug its power and plug it back in.

## The Date and time page

The page shows two clocks side by side: **This device** and **This browser** (the phone or computer you're using), each with its date and offset from UTC. Under them, a sentence says whether they agree, or how far apart they are and whether their time zones differ.

* **Set from this browser** sends your browser's time and time zone to the device. If the device already has its time from the internet, it keeps that time, and only the time zone changes. Otherwise it takes your browser's time. If the device doesn't know your browser's time zone, which can happen when your phone or computer has a newer list of zones, it still takes the time, leaves its time zone as it was, and asks you to pick one from the list.
* **Time zone**: pick a zone, type part of its name to find it, then choose **Save time zone**. The installer sets the first time zone (its `-z` option, see [Installer options](../reference/tmsetup.md)); this page changes it later. The dashboards show times, and start each day at 04:00, in the device's time zone.
* **Keep time from the internet** turns internet time on or off. The sentence under the switch says where the device's time comes from now.

Changing the time zone restarts Frigate, Node-RED, and the web proxy, so they all use the new zone. The page stops answering for a moment, and traffic isn't counted for about a minute.

Moving the clock ahead by more than about 20 seconds stops Frigate's camera feed, and a move of a few minutes can stop it until Frigate restarts. So when a change moves the clock ahead by that much, the device restarts Frigate and the page says so. Traffic isn't counted for about a minute. Moving the clock back restarts nothing, unless internet time briefly puts the device's later time back while it's being set, and then the page says so.

!!! info "When the device has no internet"

    A Raspberry Pi keeps no time while it's off, unless it has a clock battery. A device without internet then starts with a clock that may be wrong. The Status page's **Clock** check shows a warning that no time source is reachable, or a problem if the date is before 2026. Open **Date and time** on your phone or computer and choose **Set from this browser**. The clock is usually behind after a power-off, so this moves it ahead and restarts Frigate; the camera is back in about a minute. Internet time stays on, so the device corrects its clock by itself once it's online; until then the warning stays. If the device's clock was ahead, turning internet time back on puts that wrong time back, so the device sets your time again, leaves internet time off, and the page says so. Turn on **Keep time from the internet** once the device is online. If that puts the wrong time back for a moment, the device restarts Frigate; the camera is back in about a minute. If a later correction stops the camera, the Status page offers **Restart Frigate**. A device that is never online keeps time from its own clock, which drifts; set it again now and then.

## What viewers see

Viewers see all four pages, but can't change anything:

* **Status**: the same checks, without the Restart and Re-scan buttons.
* **Device**: the card and the software versions, without **Tokens and keys**, **Diagnostics**, and **Power**.
* **Detection**: the models and the label lists, without the action buttons and the Frigate+ key form; see [Choose the detection model](detection.md#the-detection-page).
* **Date and time**: the clocks, the time zone, and where the time comes from, without the button, the zone picker, or the switch.
