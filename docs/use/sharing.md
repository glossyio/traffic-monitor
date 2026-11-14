---
description: Choose whether a Traffic Monitor shares its data with a server, which server, and how much of its location goes with it; check that the server gets the data; and what an update or the installer's -f flag does to your choices.
---

# Share data

A Traffic Monitor shares nothing until an administrator turns it on. The control app's **Sharing** page, in its menu, sets where the device uploads its data and what goes with it. Everyone who is logged in can see what the device shares and how the server last answered. Only the administrator can change anything.

![The Sharing page on a phone: the saved settings, the choice of server, the access token, the three choices about what the device shares, the notice, and Save](../assets/images/sharing-page.png){ width="300" }

## Choose the server

| Server | What differs |
|---|---|
| **Traffic Monitor's server** | The default. Before you turn sharing on, or add a choice to it, you read the notice that says what is done with the data. The public map choice is offered only for this server. |
| **Your own ThingsBoard server** | You give its host, its protocol (`https` or `http`), and, if it isn't on the standard port, its port. The notice and the public map don't apply to it. Once data leaves the device, it's your responsibility to make that server honour the choices you make on this page. |

Changing the server turns off the exact location and the public map. Each choice is given for one server, so tick them again for the new one.

## Set the access token

The server gives each device an access token. Enter it in **Access token** and choose **Save token**. The page says whether a token is set and its last four characters, and never shows it back. A token takes letters, digits, and `. _ ~ -`, and is up to 256 characters long.

Saving the token restarts Node-RED, which takes about thirty seconds. The device counts nothing while it restarts. **Share data** can't be ticked until a token is set.

## Choose what the device shares

Each of the three choices starts off, is ticked on its own, and is turned off in the same place: untick it and choose **Save**. **See an example** under each one shows what is sent, with made-up values.

| Choice | What it sends | What it doesn't send |
|---|---|---|
| **Share data** | Each [event](../data-and-payloads/events-payload.md) with its speed and direction, the [radar](../data-and-payloads/radar-payload.md) and [air quality](../data-and-payloads/air-quality-aq-payload.md) readings, and the device's system health: its software versions, name on the network, time zone, serial number, temperature, and disk use. With them goes where the device is, as the database stores it: the place's id and its location rounded to about 1 km, unless you chose another [precision](location.md#choose-the-precision), and the way each sensor faces. Turning this off stops every upload. | Images, video, plate reads, the device's settings, its Wi-Fi details, and the descriptions you give places. |
| **Share the exact location** | The exact coordinates of the place in use, with its id, for the server's operator to use and not to publish. It needs **Share data**, and over your own server it needs `https`. Nothing is sent until the place in use has a location. | Any place but the one in use. |
| **Show this device on the public map** | A point rounded to about 100 m, and nothing else about where the device is. It needs **Share data**, and it's offered for Traffic Monitor's server only. The box says **Not live yet** until a release opens the map. | The exact location. |

For Traffic Monitor's server, the page asks you to read the notice, and to tick **I've read the notice**, when a save turns **Share data** on, switches to Traffic Monitor's server, or adds a choice under a notice that has changed. A save that only keeps or turns off choices never asks. When the notice changes, the device keeps sharing as you set it, and asks an administrator to read the new version; a choice you add after that waits for you to read it.

!!! info "The exact location is for you to give or keep"

    The database stores the location rounded, so a shared copy of the database carries the rounded location only. The exact location leaves the device only under **Share the exact location**, or in the file the Location page's [**Export exact locations**](location.md#export-the-exact-locations) saves for you.

## What the server already has

Turning a choice off stops the device sending. What the server already received stays there. To ask for it to be deleted, use the contact in the notice (for Traffic Monitor's server) or ask the operator of your own server.

## Check that the server gets the data

The **Server status** line on the Sharing page, and the **Sharing server** check in the Apps group of the [Status page](device-health.md#the-status-page), say how the server last answered. The device checks again after a save while it waits for the first upload. The control app never contacts the server itself: Node-RED records how each upload went.

| Status | Meaning and what to do |
|---|---|
| Off | Nothing is uploaded. |
| Waiting for the first upload | Sharing is on and no upload has been sent since the settings loaded. The device sends system health every five minutes. |
| Accepted an upload 4 minutes ago | The server is taking the data. |
| No upload accepted for a while | The server hasn't accepted an upload for 15 minutes. Check the device's internet connection on the [Network page](wifi-hotspot.md#the-network-page). |
| Can't be reached | The device couldn't reach the server. The device keeps counting and recording, and an upload that fails isn't sent again, so the server misses what the device sent while it was offline. This is a warning, because an offline device is normal. |
| Refused the token | The server doesn't accept this device's token. The Status page's **Check the token** link opens the token's section. This is a problem. |
| Refused an upload | The server turned down what the device sent. Ask the server's operator. This is a problem. |
| Answered with an error | The server had an error. This is a warning; it usually passes. If it doesn't, ask the operator. |
| Not known | Node-RED isn't answering, so the status isn't known. See the Node-RED check in the Apps group. |

The **Sharing** check, in the Configuration group, says what is shared: **Not sharing**, **Sharing data**, or **Sharing data and the exact location**, and whether the public map is on. It's a warning, with a **Review sharing** link, when the page needs a look: after an [update](#after-an-update), when no one has read the notice yet or it has changed, or when the [`sharing` block](../configuration/node-red-config.md#sharing) in `config.yml` has a value the device ignores. Opening the Sharing page and choosing **Save** rewrites that block.

## After an update

A device that already uploaded before it had these choices keeps uploading, with the location as the database stores it. The exact location stops until an administrator turns it on. The Status page shows **Review sharing** until an administrator chooses **I've reviewed this** on the Sharing page or saves the page. Until someone reads the notice and saves the page, the Sharing check also says so.

The upload of the device's settings, and the Backup & Restore section of the legacy dashboard, are removed while they are reworked.

An old `config.yml` that still has the placeholder server `tb.server.com`, with the upload off, gets Traffic Monitor's server when the installer runs.

## What the installer's `-f` does to sharing

Running the installer with `-f` writes a fresh `config.yml` with the upload off and no `sharing` block, so every choice is turned off, and none is restored afterwards. The access token stays, because the device keeps it with its other secrets. Turning the upload back on by editing the file shares the rounded data only: the exact location and the public map are never turned on from the file. Choose them again on this page.

## Where it's stored

The page writes the server and the choices to [`config.yml`](../configuration/node-red-config.md#thingsboard), and keeps a record of each choice, with when it was made and which notice it was under, in the control app's own database. The `config.yml` copy is what Node-RED reads, so a choice you make by editing the file has no effect.
