---
description: Reach a Traffic Monitor at the roadside through its own Wi-Fi hotspot, see the unit's network addresses, change the hotspot's name and password, hide or turn off the hotspot, and learn when the hotspot is on.
---

# Wi-Fi and the hotspot

When a Traffic Monitor's Wi-Fi isn't on a network it knows, the unit runs a hotspot of its own. The hotspot is how you reach a unit at the roadside, where there's no router. It runs whether or not the unit is also on Ethernet.

The hotspot's name is `TM-` and four characters from the unit's serial number, such as `TM-4F2A`, until an administrator [renames it](#rename-the-hotspot). It uses WPA2 on the 2.4 GHz band. The [Status page](device-health.md#the-status-page) shows its state.

## Join the hotspot

1. Find the hotspot's name and password on the unit's card. The card is the printout that came with a pre-built unit; for a unit you installed yourself, the installer shows it at the end of its run on the device. An administrator can also show the password on the [Network page](#the-network-page), and `sudo tm-control card` on the unit prints it again, together with the setup code while the unit is [unclaimed](control-app.md#claim-the-device).
2. On your phone, join the hotspot with that password. Your phone may say the network has no internet. Stay connected.
3. The phone's sign-in window opens the control app by itself, on its login or setup page. If it doesn't, open `http://10.42.0.1/` in a browser. The unit's `.local` name, `http://<hostname>.local/`, also works.

The hotspot has no internet, and a phone on it reaches only the unit. Nothing on the unit's Ethernet or home network is reachable from the hotspot.

### Phones

* **Android 17:** the sign-in window is the way in. Android 17 browsers can't open the unit while the phone is on its hotspot, so don't close the window until you're done. See [the Android 17 entry](../help-and-faq/frequently-asked-questions.md#troubleshooting) if the page doesn't open on your home network either.
    * The database and JSON downloads on the [Data export page](../ui/database.md) save from the sign-in window. The unit prepares the database twice there, once for the window and once for the phone's downloader, so the wait before a database download starts is about double.
    * **Download diagnostics** on the Device page doesn't save from the sign-in window: the phone says "Could not download". Download it from a computer on the unit's network instead.
    * Frigate's downloads, such as a snapshot, don't save from the sign-in window either.
* **iPhone:** to stay on the hotspot and save downloads, tap **Cancel** on the sign-in sheet and choose **Use Without Internet**. Then open `http://10.42.0.1/` or the unit's `.local` name in a browser. The login and setup pages show that name while the phone is on the hotspot. Without that choice the iPhone goes back to another network it knows, and a download in progress is cut off. The sign-in sheet itself shows a downloaded file's contents instead of saving it.

Tested with a Pixel 7 on Android 17 and with Firefox on an iPhone on iOS 18.7, in November 2026.

## The Network page

**Network** in the [control app](control-app.md)'s menu shows how to reach the unit and what it is connected to. Everyone who is signed in sees:

* **This device:** the unit's name and its `.local` name, such as `tm-ab12` and `tm-ab12.local`.
* **Ethernet** and **Wi-Fi:** whether each is connected, and for each its MAC address, IP address, gateway, and DNS servers. The Wi-Fi line says which network the unit is on, with its signal, or that it is on its own hotspot. A unit without Ethernet has no Ethernet line, and a unit without a built-in radio says so.
* **Internet:** whether the unit reaches the internet. An offline unit says **Not reachable**, which is normal.
* **Hotspot:** whether it is on, its name, whether the name is hidden, and the two addresses it answers on.

Every name and address has a **Copy** button. If the network service doesn't answer, the page says so and shows only the names.

The [Device page](device-health.md#the-device-page) shows the same addresses in a short summary, with a link to this page.

!!! tip "Find the MAC address"
    A router set to admit listed devices only needs the unit's Wi-Fi **MAC address**. Copy it from the Wi-Fi block of the Network page, and add it to the router's list.

Viewers see the hotspot's state, name, and addresses, and nothing else. They never see its password or a control. Administrators get the controls described in the rest of this page: show or change the password, rename the hotspot, hide its name, and turn it on or off.

!!! info "Changes restart the hotspot"
    A change to the hotspot's name, password, or hidden setting restarts it when it is up. Phones on it are disconnected, and each phone must rejoin by hand. When you use the Network page from a phone on the hotspot, the page stops answering when you save. Join the hotspot again, then reload the page. The page warns you before each change.

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

### Turn the hotspot off

1. Sign in as an administrator and open **Network**.
2. Under **Hotspot**, switch off **Hotspot on**.
3. Read the warning, and choose **Turn off** if you still want to.

The warning says: "With the hotspot off, this unit has no wireless way in when its Wi-Fi network is missing. You would need an Ethernet cable." The hotspot stops now and doesn't start by itself again, and phones on it are disconnected. To turn it on again, switch **Hotspot on** back on. The unit then starts the hotspot as the table above describes; a unit that is on a saved network starts it when that network is lost.

## The password

The installer makes the password on the unit, at random, when it sets up the hotspot. It's twelve letters and digits in three groups, such as `ABCD-EFGH-JKLM`, and it's different on every unit. It never comes from the serial number, so knowing the name tells nobody the password.

The unit keeps it in `/etc/traffic-monitor/secrets/hotspot_password`, readable only by root and the installing user's group (`tmadmin` unless you installed with `-g`). The installer shows the card on the terminal and keeps the password out of its log; a run from another computer with `-H` prints only a reminder of the command.

### Show the password

On the Network page, an administrator chooses **Show** next to **Password**. The page asks the unit for the password each time and forgets it again when you choose **Hide**, change anything, or leave the page. The control app records each time an administrator shows it.

If you can't sign in, run `sudo tm-control card` on the unit instead. Over Ethernet or SSH works when you're locked out of the hotspot.

### Change the password

1. Sign in as an administrator and open **Network**.
2. Next to **Password**, choose **Change**. A unit whose hotspot has no password offers **Set a password** here.
3. Type the new password, 8 to 63 letters, digits, and symbols with no space at either end.
4. Write the password down, then choose **Change password**.

The hotspot restarts with the new password, and phones on it are disconnected. Each phone must rejoin by hand, with the new password. The page types the password in the open and asks for it only once, so you see what you write down.

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

## Rename the hotspot or hide its name

An administrator can change the name phones see, and hide it, on the Network page.

### Rename the hotspot

1. Open **Network**, and next to the hotspot's **Name**, choose **Change**.
2. Type the new name. It takes 1 to 32 bytes, so fewer characters if it has accents or emoji, with no space at either end.
3. Choose **Change name**.

The hotspot restarts, and each phone must join the new name by hand. A printed card still shows the old name. `sudo tm-control card` shows the new one.

### Hide the name

1. Open **Network**, and switch on **Hide the name**.
2. Read the warning, and choose **Hide the name**.

The warning says: "The hotspot is still on and can still be found by scanning. Only its name is hidden." Hiding the name doesn't stop anyone from finding the hotspot, so it isn't a lock. A phone no longer lists the hotspot by name. On Android, add the network by hand: choose **Add network**, type the name and the password, and tick **Hidden network**. Without that, the phone never connects. Switch **Hide the name** off to show the name again.

## A hotspot you set up by hand

A hotspot you made yourself in NetworkManager is kept. When a unit has no profile named `tm-hotspot`, the installer takes over your access-point profile, the one that starts by itself and was used last, renames it `tm-hotspot`, and stops any other access point from starting. Its name on air, password, band, and hidden setting stay as you set them. The installer sets the profile's address to `10.42.0.1` and its priority below your saved networks, and copies the password into the password file.

A hand-made hotspot with no password shows as a problem on the Status page, because anyone nearby can join it. The Status page's **Set a password** link opens the Network page. There, next to **Password**, choose **Set a password** and follow the steps in [Change the password](#change-the-password). The installer then keeps the profile's password the same as the password file's. An empty file tells the installer to leave the hotspot's security alone.

A hand-made hotspot with a hidden name keeps it. Manage it as in [Hide the name](#hide-the-name).

## Who can see the hotspot

A hotspot on a pole is visible to anyone passing, and public Wi-Fi maps record where names are seen. The name `TM-` and four characters shows that a Traffic Monitor is nearby and doesn't say where it is. [Hiding the name](#hide-the-name) makes the hotspot harder to spot in a list, but a scan still finds it. Only turning the hotspot off prevents it, with the cost described in [Turn the hotspot off](#turn-the-hotspot-off). The password is what keeps people out of the control app. [Control app and login](control-app.md) explains what its login protects.

## The Wi-Fi country

Wi-Fi rules differ by country, and a radio with no country set uses limited worldwide settings. The installer asks for the country, as a two-letter code such as `US` or `GB`, when the unit has none. Press Enter to accept `US`. With `-y`, it keeps the unit's country, or sets `US` when there is none. To set it without being asked, or to change it, run the installer with `-w`:

```bash
bash traffic-monitor/script/tmsetup.sh -t wifi -w GB
```

The change applies at once, with no reboot. The Status page warns while no country is set.

## Limits

* A network the unit is also connected to that uses `10.42.0.x` addresses clashes with the hotspot's fixed address. Give that network another range.
* The hotspot runs on the built-in radio, `wlan0`. If a USB Wi-Fi adapter takes that name, the hotspot stays off, and the Status page says so. Unplug the adapter and reboot.
