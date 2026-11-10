---
description: Reach a Traffic Monitor at the roadside through its own Wi-Fi hotspot, find or change the hotspot's password, and learn when the hotspot is on.
---

# Wi-Fi and the hotspot

When a Traffic Monitor's Wi-Fi isn't on a network it knows, the unit runs a hotspot of its own. The hotspot is how you reach a unit at the roadside, where there's no router. It runs whether or not the unit is also on Ethernet.

The hotspot's name is `TM-` and four characters from the unit's serial number, such as `TM-4F2A`. It uses WPA2 on the 2.4 GHz band. The [Status page](device-health.md#the-status-page) shows its state.

## Join the hotspot

1. Find the hotspot's name and password on the unit's card. The card is the printout that came with a pre-built unit; for a unit you installed yourself, the installer shows it at the end of its run on the device. `sudo tm-control card` on the unit prints it again, together with the setup code while the unit is [unclaimed](control-app.md#claim-the-device).
2. On your phone, join the hotspot with that password. Your phone may say the network has no internet. Stay connected.
3. The phone's sign-in window opens the control app by itself, on its login or setup page. If it doesn't, open `http://10.42.0.1/` in a browser. The unit's `.local` name, `http://<hostname>.local/`, also works.

The hotspot has no internet, and a phone on it reaches only the unit. Nothing on the unit's Ethernet or home network is reachable from the hotspot.

### Phones

* **Android 17:** the sign-in window is the way in. Android 17 browsers can't open the unit while the phone is on its hotspot, so don't close the window until you're done. See [the Android 17 entry](../help-and-faq/frequently-asked-questions.md#troubleshooting) if the page doesn't open on your home network either.
    * The database and JSON downloads on the [Data export page](../ui/database.md) save from the sign-in window. The unit prepares the database twice there, once for the window and once for the phone's downloader, so the wait before a database download starts is about double.
    * **Download diagnostics** on the Device page doesn't save from the sign-in window: the phone says "Could not download". Download it from a computer on the unit's network instead.
    * Frigate's downloads, such as a snapshot, don't save from the sign-in window either.
* **iPhone:** to stay on the hotspot and save downloads, tap **Cancel** on the sign-in sheet and choose **Use Without Internet**. Then open `http://10.42.0.1/` or the unit's `.local` name in Safari. The login and setup pages show that name while the phone is on the hotspot. Without that choice the iPhone goes back to another network it knows, and a download in progress is cut off. The sign-in sheet itself shows a downloaded file's contents instead of saving it.

Tested with a Pixel 7 on Android 17 and an iPhone on iOS 18.7, in November 2026.

## When the hotspot runs

The hotspot yields to the networks the unit has saved. A unit joins a saved network that's in range, and the hotspot runs when none is.

| Situation | What happens |
|---|---|
| The unit starts with a saved network in range | It's on the network within a minute. The hotspot stays off. |
| The unit starts with no saved network in range | The hotspot is up about 15 seconds after the unit starts. |
| The unit's Wi-Fi network disappears | The hotspot starts about 75 seconds later. |
| A saved network has the wrong password | The hotspot is away for about a minute while the unit tries the network, then comes back. |

While the hotspot is up and nobody is joined to it, the unit looks for its saved networks every 5 minutes and joins one it hears. A network that won't join is tried again about 10 minutes after the failure, then about 20 minutes after the next one, then about 65 minutes after each further failure. While a phone is joined to the hotspot, the unit doesn't look, so nothing interrupts the phone.

The Status page's Hotspot check says which of these the unit is in, and its **Restart the hotspot** button has the unit look at its radio at once.

??? note "Turn the hotspot off"

    A unit with its hotspot off has no wireless way in when its Wi-Fi network is missing. To stop the hotspot from starting by itself, run `sudo nmcli connection modify tm-hotspot connection.autoconnect no`. The installer leaves that setting as you set it. To turn the hotspot on again, set it to `yes`.

## The password

The installer makes the password on the unit, at random, when it sets up the hotspot. It's twelve letters and digits in three groups, such as `ABCD-EFGH-JKLM`, and it's different on every unit. It never comes from the serial number, so knowing the name tells nobody the password.

The unit keeps it in `/etc/traffic-monitor/secrets/hotspot_password`, readable only by root and the installing user's group (`tmadmin` unless you installed with `-g`). To read it, run `sudo tm-control card` on the unit. Over Ethernet or SSH works when you're locked out of the hotspot. The installer shows the card on the terminal and keeps the password out of its log; a run from another computer with `-H` prints only a reminder of the command.

### Change the password

1. On the unit, open the password file for editing with `sudoedit /etc/traffic-monitor/secrets/hotspot_password`. Replace its contents with one line of 8 to 63 characters.
2. Run `bash traffic-monitor/script/tmsetup.sh -t wifi`. The installer sets the hotspot's password to the file's.
3. Restart the hotspot, or wait for its next start. The installer never restarts a hotspot that is up, so a phone joined to it stays joined until then. To apply the password at once, reboot the unit, or run `sudo nmcli connection up tm-hotspot`. Every phone on the hotspot drops, and each rejoins with the new password.

A screen in the control app for changing the password is planned.

### For sellers

`sudo tm-control card --json` prints the card's values as JSON, for a label or a packing slip:

```json
{
  "hostname": "tm-01",
  "local_url": "http://tm-01.local/",
  "hotspot": {"name": "TM-4F2A", "password": "ABCD-EFGH-JKLM", "url": "http://10.42.0.1/"},
  "claimed": false,
  "setup_code": "ABCD-EFGH"
}
```

`setup_code` is `null` once the unit is claimed. The command needs `sudo`, and it prints to the terminal only. Nothing stores or logs the card, so don't paste the output where others can read it.

## A hotspot you set up by hand

A hotspot you made yourself in NetworkManager is kept. When a unit has no profile named `tm-hotspot`, the installer takes over your access-point profile, the one that starts by itself and was used last, renames it `tm-hotspot`, and stops any other access point from starting. Its name on air, password, band, and hidden setting stay as you set them. The installer sets the profile's address to `10.42.0.1` and its priority below your saved networks, and copies the password into the password file.

A hand-made hotspot with no password shows as a problem on the Status page, because anyone nearby can join it. To set a password, run these two commands on the unit, with a password of 8 to 63 characters in place of `<password>`:

```bash
sudo nmcli connection modify tm-hotspot 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.proto rsn 802-11-wireless-security.pairwise ccmp 802-11-wireless-security.group ccmp 802-11-wireless-security.psk '<password>'
sudoedit /etc/traffic-monitor/secrets/hotspot_password
```

In the file, write the same password on one line. That keeps the card right, and the installer then keeps the profile's password the same as the file's. An empty file tells the installer to leave the hotspot's security alone. The new password applies when the hotspot next starts; see step 3 of [Change the password](#change-the-password).

??? question "A hotspot with a hidden name"

    If you hid your hand-made hotspot's name, a phone doesn't list it. On Android, choose **Add network**, type the name, and tick **Hidden network**.

## Who can see the hotspot

A hotspot on a pole is visible to anyone passing, and public Wi-Fi maps record where names are seen. The name `TM-` and four characters shows that a Traffic Monitor is nearby and doesn't say where it is. The password is what keeps people out of the control app. [Control app and login](control-app.md) explains what its login protects.

## The Wi-Fi country

Wi-Fi rules differ by country, and a radio with no country set uses limited worldwide settings. The installer asks for the country, as a two-letter code such as `US` or `GB`, when the unit has none. Press Enter to accept `US`. With `-y`, it keeps the unit's country, or sets `US` when there is none. To set it without being asked, or to change it, run the installer with `-w`:

```bash
bash traffic-monitor/script/tmsetup.sh -t wifi -w GB
```

The change applies at once, with no reboot. The Status page warns while no country is set.

## Limits

* A network the unit is also connected to that uses `10.42.0.x` addresses clashes with the hotspot's fixed address. Give that network another range.
* The hotspot runs on the built-in radio, `wlan0`. If a USB Wi-Fi adapter takes that name, the hotspot stays off, and the Status page says so. Unplug the adapter and reboot.
