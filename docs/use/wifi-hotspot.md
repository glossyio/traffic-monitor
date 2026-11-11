---
description: Reach a Traffic Monitor at the roadside through its own Wi-Fi hotspot, put the unit on a Wi-Fi network from the control app, manage its saved networks, change the hotspot's name and password, hide or turn off the hotspot, and learn when the hotspot is on.
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
* **Wi-Fi networks:** the networks the unit has saved and the ones it heard the last time it looked. See [Put the unit on a Wi-Fi network](#put-the-unit-on-a-wi-fi-network) and [Saved networks](#saved-networks).
* **Hotspot:** whether it is on, its name, whether the name is hidden, and the two addresses it answers on.

Every name and address has a **Copy** button. If the network service doesn't answer, the page says so and shows only the names.

The [Device page](device-health.md#the-device-page) shows the same addresses in a short summary, with a link to this page.

!!! tip "Find the MAC address"
    A router set to admit listed devices only needs the unit's Wi-Fi **MAC address**. Copy it from the Wi-Fi block of the Network page, and add it to the router's list.

Viewers see the lists of networks, the hotspot's state, name, whether the name is hidden, and addresses, and nothing else. They never see its password or a control. Administrators get the controls described in the rest of this page: put the unit on a Wi-Fi network, change the saved networks, show or change the hotspot's password, rename the hotspot, hide its name, and turn it on or off.

!!! info "Changes restart the hotspot"
    A change to the hotspot's name, password, or hidden setting restarts it when it is up. Phones on it are disconnected, and each phone must rejoin by hand. When you use the Network page from a phone on the hotspot, the page stops answering when you save. Join the hotspot again, then reload the page. The page warns you before a change that restarts the hotspot, before you turn the hotspot off, and before you hide its name. Turning the hotspot on doesn't ask.

## Put the unit on a Wi-Fi network

An administrator can put the unit on a Wi-Fi network from the Network page, without a cable or a keyboard. The unit tests the network first, and only switches to it once the test has passed and a countdown has ended.

1. Open **Network**. Under **Wi-Fi networks**, choose **Refresh** to have the unit look for networks. It takes about 4 seconds, and a phone on the hotspot pauses for a few seconds while the unit looks. **Nearby networks** lists what it heard, strongest first, and says how long ago it looked.
2. Choose **Join** next to the network, and read what the dialog says will happen. It shows the unit's Wi-Fi MAC address too.
3. Type the network's password, and choose **Test and join**. The page shows the password as you type it, and asks only once.

The unit doesn't save the network or its password at this point. Until the switch, the network exists only in the unit's memory, so a wrong password never reaches the microSD card.

### The test

A test takes up to about a minute, and the unit's radio is busy with it. If the unit was on its hotspot, the hotspot is away for the test and a phone on it is disconnected. The hotspot is back within a few seconds after the test ends. Join it again by hand, and reload the page to see the result. If the unit was on another network, it leaves that network for the test and returns to it. Until the test ends, the page refuses every other Wi-Fi change.

The test asks the network for an address, then makes one DNS question and one request to `connectivity-check.ubuntu.com` to see whether the internet is reachable. The unit comes back to where it was either way. To test a network the unit has saved already, choose **Join** and keep its saved password, or enter a new one.

A card at the top of the Network page shows the test as it runs. Administrators also see a line with a **See it** link on the [home page](home-page.md), so you can find the result from there.

### The result and the countdown

When the test passes, the card says **`<name>` works** and shows:

* the address the unit got on that network, and its `.local` name, which you can use to reach it there;
* the unit's Wi-Fi MAC address;
* whether the internet is reachable there.

Below that, a countdown starts at 5 minutes: **Joining `<name>` in 4:32**. Use the time to join the same network with your phone or computer, so you can open one of the addresses once the unit has switched.

* **Switch now** ends the countdown, and the unit joins at once.
* **Cancel** ends it, and the unit stays where it is. Nothing is saved.
* If you do nothing, the unit joins when the countdown ends.

When the unit joins, the network is saved and the unit uses it. If the unit was on the hotspot, the hotspot stops. A phone on the hotspot loses it, so join the network yourself and open one of the addresses from the card. The result stays on the page until you choose **Dismiss**.

!!! info "A network with a sign-in page"
    Some networks, such as a hotel's or a cafe's, give the unit an address but make a device open a web page before it reaches the internet. The unit can't complete that page. The card says "Joined, but this network needs a sign-in page, so the unit has no internet there." The unit can still join the network and be reached on it, and you can switch to it if you want that.

### If the test fails

The card says why, and the unit is back where it was. Nothing is saved for a new network.

| The card says | What it means |
|---|---|
| **`<name>` isn't in range right now, so nothing was tried** | The unit didn't hear the network when it checked, so it left its radio alone. Choose **Refresh** and try again from a place with a better signal. |
| **The unit couldn't join `<name>`** | Usually a wrong password. This fails after about 25 seconds. A router set to admit listed devices only also refuses the unit until you add the unit's Wi-Fi MAC address, which the card and the dialog show, to its list. |
| **`<name>` let the unit in but gave it no address** | The unit connected, but the network's DHCP gave it nothing. This fails after about 45 seconds. Try again later, or check the network's address range. |
| **The unit was busy with its Wi-Fi** | Another Wi-Fi change was under way. Try again in a minute. |
| **The test couldn't run** | The unit couldn't prepare to come back, so it left its radio alone, or it hit an error it didn't expect. It is back where it was. |
| **The test of `<name>` was interrupted** | The test stopped partway, for example because the unit lost power. The unit goes back to where it was within a minute and a half. |
| **The test passed, but the unit couldn't join `<name>` when the countdown ended** | The unit is back where it was. The network stays saved, and the unit tries it again by itself after a wait of 5, 15, then 60 minutes. |

A saved network that fails is kept, because the cause may be temporary. A new network that fails is not saved.

## Saved networks

**Saved networks** lists the networks the unit joins by itself. Above the list the page says: "The unit joins the first of these it finds." The order is the order the unit tries them in, so the network at the top wins when more than one is in range. A network the unit joined from the page goes to the top of the list.

Each network shows whether it is **Joined**, **In range**, or **Not in range**, and flags a network that is **Hidden** or **Not joined by itself**. A network saved through Raspberry Pi Imager's Wi-Fi settings shows here too, as an ordinary saved network.

* **Move up** and **Move down** change a network's place in the order. Only the networks the unit joins by itself have a place.
* **Forget** deletes a saved network, after a question. The unit no longer joins it. When it isn't the network in use, nothing else changes.
* **Forget** on the network in use makes the unit leave it. The question says so, and says what happens next. The hotspot starts within about 5 seconds, and a page opened over that network loses the unit, so join the hotspot and open `http://10.42.0.1/`. With the hotspot turned off, the question warns that the unit then has no wireless way in, and that you would need an Ethernet cable.

### Couldn't join

A saved network that the unit failed to join shows **Couldn't join**. The unit tries again by itself, after a wait of 5, 15, then 60 minutes; [When the hotspot runs](#when-the-hotspot-runs) gives the times a person sees. Joining the network by hand from the page, with the right password, tests it again at once.

## When the hotspot runs

The hotspot yields to the networks the unit has saved. A unit joins a saved network that's in range, and the hotspot runs when none is.

| Situation | What happens |
|---|---|
| The unit starts with a saved network in range | It's on the network within a minute. The hotspot stays off. |
| The unit starts with no saved network in range | The hotspot is up about 15 seconds after the unit starts. |
| The unit's Wi-Fi network disappears | The hotspot starts about 75 seconds later. |
| A saved network has the wrong password | The hotspot is away for about a minute while the unit tries the network, then comes back. |
| You join a network from the page | The hotspot is away for up to a minute for the test, then comes back. When the countdown ends, or you choose **Switch now**, the unit joins the network and the hotspot stops at once. |
| You forget the network in use | The hotspot starts within about 5 seconds. |

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
4. Write the password down, then choose **Change password**, or **Set password** on a unit that has none.

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

* The page can't join an open network, a hidden network (a saved hidden network included), a WPA3-only network, or a network that asks for a user name as well as a password (an enterprise network). It lists them and says why. A network that offers both WPA2 and WPA3 is joined as WPA2. The page doesn't complete a sign-in page, it only reports one.
* One test or countdown runs at a time, and the page joins over IPv4 only.
* A network the unit is also connected to that uses `10.42.0.x` addresses clashes with the hotspot's fixed address. Give that network another range.
* The hotspot runs on the built-in radio, `wlan0`. If a USB Wi-Fi adapter takes that name, the hotspot stays off, and the Status page says so. Unplug the adapter and reboot.
