---
description: Use the control app's Status, Device, and Date and time pages to see whether a Traffic Monitor works, restart what stopped, download diagnostics, reboot, and set the clock.
---

# Check and fix the device

Three pages in the [control app](control-app.md)'s menu tell you whether the device works and let the administrator fix the common problems from a phone, without SSH:

* **Status** checks the services, apps, settings, hardware, and clock, and offers a fix for what's wrong.
* **Device** shows the device's facts and software versions, and has the diagnostics download, reboot, and shut down.
* **Date and time** compares the device's clock with your phone's and sets it.

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
| Services | Each Traffic Monitor service: running, stopped, starting, or running after restarts that followed failures. Frigate restarts itself when you save its config; that doesn't count as a failure. |
| Apps | Frigate answers and gets frames from each camera. Node-RED answers, loaded `config.yml` without errors, and has its database at the version this install expects. The camera streams run. The MQTT broker requires its login while port 1883 is open to the network. |
| Configuration | Frigate and `config.yml` agree on the names that link them: each Frigate camera is enabled in `config.yml`, it has the zones `zone_capture`, `zone_near`, `zone_far`, and `zone_radar`, each radar under `sensors.radars` is named after one of the `TM_RADAR_SERIAL_PORT_` variables in `node-red-tm.env`, each camera's radar is enabled, and the location values are valid. See [config.yml settings](../configuration/node-red-config.md) and [First-time setup](../setup-guide.md). |
| Hardware | Each AI accelerator, from plugged in to used by Frigate, or a warning when there's none and Frigate detects on the CPU. The video decoder Frigate uses for the camera. Each radar, from plugged in to read by Node-RED. |
| Device | Free storage (a warning under 2 GB, a problem under 512 MB), free memory (a warning under 200 MB), the processor's temperature (a warning from 80 °C, a problem from 85 °C), and the power supply: whether the Pi ran short of power or slowed itself down since it started. |
| Date and time | Whether the clock was ever set, and whether it keeps time from the internet. |

### Fix a problem

A check that isn't passing offers one of these:

* **A Restart button**, such as **Restart Frigate**, for a service that stopped or keeps failing. The device asks first and says what you'll notice, for example that traffic isn't counted while Frigate restarts. A note under the button says when the restart is under way.
* **Re-scan hardware**, at the end of the Hardware group while one of its checks isn't passing. It runs every check again at once, so you don't wait for the next check after you plug a device back in or follow the check's advice.
* **A link** to the page that fixes it, such as **Set the date and time**, or **Diagnostics** on the Device page.
* **A sentence** with the next step, such as rerunning the installer for Node-RED (`tmsetup.sh -t node-red-tm`; see [Installer options](../reference/tmsetup.md)).

The control app can't restart itself. If it stops, see [If the control app is down](control-app.md#if-the-control-app-is-down).

## The Device page

The card at the top shows the device's name, its Raspberry Pi model and memory, the Traffic Monitor version, the serial number, how long it has been running, its free storage, the processor's temperature, and the power supply's state. **Software** lists the versions of Frigate, Node-RED, go2rtc, nginx, and the Hailo driver if installed, the Traffic Monitor commit, the operating system, and the kernel.

### Download diagnostics

When you ask for help, send the diagnostics with your question. It's a text file with the device's facts, its date and time settings, every status check, the services' states, what the installer installed and found, and the last 50 lines of each service's log. Passwords, keys, tokens, and the setup code are replaced with `<redacted>`. The file names the device and holds its serial number.

* **Download diagnostics** saves the file.
* **Copy** puts the text on the clipboard, ready to paste into a message. If the browser doesn't allow it, the page shows the text in a box, already selected, for you to copy.

### Reboot or shut down

**Reboot the device** and **Shut down the device** each ask before they act. A reboot takes about two minutes, during which no page answers. If something such as a system update is holding the device up, or the control app isn't allowed to, the device says it can't reboot or shut down right now. Try again in a few minutes, and if it keeps happening, download the diagnostics.

!!! warning "Shut down only when you can reach the device"

    After a shutdown, nothing starts the device again from the network. To turn it back on, unplug its power and plug it back in.

## The Date and time page

The page shows two clocks side by side: **This device** and **This phone** (the browser you're using), each with its date and offset from UTC. Under them, a sentence says whether they agree, or how far apart they are and whether their time zones differ.

* **Set from this browser** sends your phone's time and time zone to the device. If the device already has its time from the internet, it keeps that time, and only the time zone changes. Otherwise it takes your phone's time. If the device doesn't know your phone's time zone, which can happen when the phone's list of zones is newer, it still takes the time, leaves its time zone as it was, and asks you to pick one from the list.
* **Time zone**: pick a zone, type part of its name to find it, then choose **Save time zone**. The installer sets the first time zone (its `-z` option, see [Installer options](../reference/tmsetup.md)); this page changes it later. The dashboards show times, and start each day at 04:00, in the device's time zone.
* **Keep time from the internet** turns internet time on or off. The sentence under the switch says where the device's time comes from now.

Changing the time zone restarts Frigate, Node-RED, and the web proxy, so they all use the new zone. The page stops answering for a moment, and traffic isn't counted for about a minute.

Moving the clock ahead by more than about 20 seconds makes Frigate think the camera stopped sending, so it restarts its camera feed. The Status page's **Cameras** check shows a problem for a minute or two, and traffic isn't counted until the feed is back. Frigate does this by itself; you don't need to restart it.

!!! info "When the device has no internet"

    A Raspberry Pi keeps no time while it's off, unless it has a clock battery. A device without internet then starts with a clock that may be wrong. The Status page's **Clock** check shows a warning that no time source is reachable, or a problem if the date is before 2026. Open **Date and time** on your phone and choose **Set from this browser**. Internet time stays on, so the device corrects its clock by itself once it's online; until then the warning stays. A device that is never online keeps time from its own clock, which drifts; set it again now and then.

## What viewers see

Viewers see all three pages, but can't change anything:

* **Status**: the same checks, without the Restart and Re-scan buttons.
* **Device**: the card and the software versions, without **Diagnostics** and **Power**.
* **Date and time**: the clocks, the time zone, and where the time comes from, without the button, the zone picker, or the switch.
