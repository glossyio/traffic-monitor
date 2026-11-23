# Places and location

The control app's **Location** page records where the device is and which way its sensors face. It also sets how precisely the database stores the location. Only the administrator sees the page, because it shows exact coordinates. A device that stays in one place works without it, so use it when you move the device, turn it, or plan to share its data.

## Places and deployments

A *place* is somewhere the device has been, is, or will be. Each place has an id such as `3f9a1c2e-si`, an optional description that only you see, and an optional location, its latitude and longitude. A place doesn't need a location: a device with none still counts and records its data, only without saying where. One place can hold sensors that face different ways, such as a corner with a radar looking down each street.

One place is always **In use**. The others are **Planned**, entered ahead of a move, or **Used**, where the device has been. Claiming a new device creates its first place, **First location**, with no location.

Each sensor at a place, facing one way, for one stretch of time, is a *deployment*. Every count and reading is stored with its deployment, so you can tell where it was taken after the device moves. Moving to another place, or turning a sensor, starts a new deployment, and the earlier ones keep what they recorded.

The exact location is kept in the control app and in Node-RED's settings file, [`config.yml`](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#deployment). The database stores the place's id and the location rounded to the [precision](#choose-the-precision) you choose.

## The Location page

**Location** is in the control app's menu, after **Cameras**. The card at the top shows the place in use: its description, its id, the location as the database stores it, the exact location, what the device [shares](https://docs.trafficmonitor.ai/dev/use/sharing/index.md), and the way each sensor faces. Then come the list of places, the exact locations ([a list](#export-the-exact-locations) and [a copy of the database](#download-the-database-with-exact-locations)), and, last, the [precision](#choose-the-precision).

Each place in the list shows its description, or **No description**, its mark (**In use**, **Planned**, or **Used**), its id, and its location as the database stores it. Select a place to open it. An open place shows:

- **Imported from your previous settings** for a place that came from an older version's data; see [Update the software](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/update/#places-after-an-update).
- When the place was first and last used, or **Not used yet**.
- How many events were recorded there, and between which dates.
- Its deployments, newest first, grouped by when they were deployed: the sensors started together sit under one date, each with the way it faced and **Correct bearing**. A radar deployed with a camera is indented under it. A sensor that ended before the rest of its group says when.
- The buttons for what you can do with the place: **Deploy here** for a planned place, **Re-deploy here** for a used one, or **Modify deployment** for the place in use; **Edit** for a planned place; **Correct location** for a used place or the place in use that has a location; and **Delete** for any place but the one in use.

**Before any place was recorded** counts the deployments that had already ended when the device got its first place. They belong to no place, and the database keeps them as they are. Deployments still running then joined that first place.

If Node-RED hasn't answered yet, as right after an update, a warning at the top says past places may be missing. Reload the page once Node-RED is running. Opening the control app's home page or Status page sets the places up too.

## Add a place

Choose **Add a place**, fill in what you know, and **Save**. The place is added as planned.

- **Description**: a name for the place, such as "Front of the school". It never leaves the device.
- **Coordinates**: the latitude and longitude, pasted from a maps app as one value, such as `45.52252, -122.69120`, or [picked on a map](#pick-the-point-on-a-map). Use a dot as the decimal mark. The device keeps five decimal places, about a metre. Use at least four, about 10 metres, for an exact location: with fewer, the form warns and says how coarse the point is (about 100 metres for three decimals, and coarser for fewer), and still saves it. Leave the field empty for a place with no location.
- **Which way each sensor faces here**: `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`, or **Not set**, for each sensor turned on in the settings.

**Use this phone's location** fills in the coordinates from your phone's location. Browsers share a location only with pages opened over HTTPS, and the device uses plain HTTP, so the form usually says to paste coordinates instead.

### Pick the point on a map

Under the coordinates, **Pick on a map** opens a map. Tap the spot to place a pin, drag the pin to the exact place, and choose **Use this point**. The form fills in the coordinates with five decimal places, and you can still change them before you save. The same button is on **Correct location**.

The map is drawn by your phone or computer, not by the device. It opens at the coordinates in the field, else at the place in use, else over the region of the device's time zone: a wide view around that city, about the size of a time zone. The device finds the region from its own time zone, so it asks no one, and uses it only when its Wi-Fi country is set and is one of the countries that time zone covers. Otherwise it opens on the whole world. The installer sets the time zone (its `-z` option, `America/Los_Angeles` unless you give another), so a device left on the installer's time zone and Wi-Fi country opens over Los Angeles until you set its time zone on the [Date and time page](https://docs.trafficmonitor.ai/dev/use/device-health/#the-date-and-time-page). Your browser asks the map's server, named in the dialog, for the pictures of the area you look at, and the device sends it nothing. The server sees the map tiles that cover the area you look at, squares of roughly one to two kilometres across, even when you zoom in as far as the map goes. That includes the area of the place in use the moment the map opens, even when you are adding a place somewhere else. Opened over the region, the map asks for tiles that cover an area thousands of kilometres across, which says little more than your phone's internet address already does. As any website does, the server also sees your phone's internet address. It never gets the exact point you choose. If the map can't load, the dialog says so and offers **Try again**; type or paste the coordinates instead.

The map isn't offered while your phone is on the device's own [hotspot](https://docs.trafficmonitor.ai/dev/use/wifi-hotspot/#phones), because the hotspot has no internet. The form says so; paste the coordinates, or open the page once the device is on your Wi-Fi.

To get coordinates from a maps app on your phone, in Google Maps press and hold the spot, then copy the coordinates shown. In Apple Maps, drop a pin; its card shows the coordinates. The phone's GPS needs no internet connection, though the app's map may not draw without one.

To change a planned place, open it and choose **Edit**. A place that has been used can't be edited; [correct it](#correct-a-wrong-location-or-bearing) instead.

## Move or turn the device

When the device moves to another place, record it from that place: **Deploy here** if the place is planned, or **Re-deploy here** if the device has been there before. When a sensor is turned to face another way, record it with **Modify deployment** on the place in use.

1. Open the place, and choose its button.
1. Check the review. For each sensor, it says whether a new deployment starts, the way the sensor faced before, and the way it faces now, which you can change. Under the sensors are what the database will store for the place and whether the device shares its data.
1. Choose **Deploy**, **Re-deploy**, or **Modify**.

The page waits while Node-RED starts the new deployments, then lists their ids, each with **Copy**. Counts from then on belong to the new deployments.

In **Modify deployment**, the review starts with each sensor's bearing as it is, and each sensor reads **Unchanged** until you change its bearing. **Modify** stays off until at least one bearing changes, and only the sensors you turned start a new deployment.

Don't deploy twice

If Node-RED hasn't loaded the new settings within about 20 seconds, the page says the settings are saved and the deployments appear once Node-RED loads them. If the connection drops while the page waits, it says the settings may already be saved. In both cases, close the dialog and check the place in the list before you deploy again.

A move usually also needs the camera's zones adjusted; see [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/#3-adjust-the-zones).

## Correct a wrong location or bearing

A correction is for a value that was entered wrong. It changes what the records already say, and starts no new deployment. If the device moved or was turned, [record that](#move-or-turn-the-device) instead.

- **Correct location**, on a used place or the place in use, takes a new latitude and longitude, typed or [picked on a map](#pick-the-point-on-a-map). Every record from the place then says it was at the new point, rounded to the precision each was stored at. For the place in use, `config.yml` takes the new point too. A point more than about 1 km from the old one looks like a move, so the page asks a second time and gives the distance. A place with no location can't be corrected to one: add a new place with the location, and deploy it.
- **Correct bearing**, on each deployment in an open place, takes the way the sensor really faced. Every record from that deployment then says so. For a deployment that is still running, `config.yml` takes the new bearing too.

Each correction can have a **Reason**, which is kept with the correction on the device. Copies of the database already downloaded, and data already uploaded, keep the old values.

## Import places from a file

To plan several places at once, choose **Import places**. Pick a CSV file, or paste its lines into the box.

- The first line is the header. It starts with `description,lat,lon`, then has one column for each sensor turned on in the settings, named as in the settings. The dialog shows this device's header.
- Each further line is one place. Leave `lat` and `lon` both empty for a place with no location. A sensor's column holds the way it faces, `n`, `ne`, `e`, `se`, `s`, `sw`, `w`, or `nw`, or nothing.
- A file can be up to 64 KiB.

For a device with the Pi camera and one radar:

```
description,lat,lon,picam_h265,TM_RADAR_SERIAL_PORT_00
Front of the school,45.52252,-122.69120,n,n
Corner by the park,,,e,e
```

Choose **Preview** to see the places the file holds and, by line number, any lines with a problem. **Import** adds the places as planned. It's offered only when every line can be read, and it adds all of them or none.

## Delete a place

Open the place and choose **Delete**, then confirm. A planned place is removed from the list. A used place's exact location is deleted with it, and the database keeps the rounded location stored with each of its records. Deleting can't be undone.

The place in use can't be deleted. Deploy another place first.

## Export the exact locations

**Export exact locations**, above the precision, saves a CSV file with one line for each place: its id, its exact latitude and longitude (empty for a place with no location), its mark, and when it was added and last changed. It has no descriptions. Use it to match a copy of the database, which holds each place's id and rounded location, with where the device really was, for analysis and mapping.

The page asks first, because the file says exactly where the device has been, and anyone you give it to can match it to the database by place id. To get the exact locations inside a copy of the database instead, see [Download the database with exact locations](#download-the-database-with-exact-locations).

## Download the database with exact locations

**Download the database with exact locations**, next to **Export exact locations**, saves a copy of the database that also holds where the device was. Use it when the person who analyzes the data should map it at the real places, and a separate list of places to match by id would be one more step.

Choose the button and read the question. It says that the copy holds the exact location of each place the device has been at, that the database on the device keeps its rounded locations, and that you should give the copy only to someone who should know where the device was. Choose **Download**. The device makes a consistent copy of the database first, so the download starts after a wait, which can take a few minutes for a large database, and the page says so. The copy needs free space about the size of the database, as the [Data export](https://docs.trafficmonitor.ai/dev/ui/database/#download-the-database) download does. If the device can't make the copy, the browser has already left the Location page and shows a plain text page with the reason instead of a file: go back to the Location page, and reload it before you try again. Once a copy has started, the button stays off until you reload the page, so that a second copy isn't started by mistake while the first is still being made.

The button is off, with the reason under it, until a place the device has been at, one marked **In use** or **Used**, has a location. A planned place doesn't count, because the device was never there.

The file is named `<hostname>_<time>_tmdb-exact-locations.tar.gz` and holds `tmdb-exact-locations.sqlite`. The name says what it is, so nobody takes it for the database you can share. On a phone joined to the unit's hotspot, see [Phones](https://docs.trafficmonitor.ai/dev/use/wifi-hotspot/#phones) for how downloads save.

### What the copy adds

The copy is the database as it is, with two more things in it:

- The table `survey_exact_location` has one row for each place: its id, and its exact latitude and longitude.
- The view `deployment_exact` is the `deployment` table with two more columns, `exact_lat` and `exact_lon`, from the place the row names.

The `deployment` table itself is not changed. Its `lat` and `lon` still hold the location rounded to the [precision](#choose-the-precision) stored with each row, so a script that reads them gets the rounded location from every file, and an exact point can't be picked up by mistake. To list where the device was and when, with each deployment's sensor, start, end, and exact point:

```
SELECT sensorName,
       datetime(entryStartDateTime / 1000, 'unixepoch') AS started,
       datetime(entryEndDateTime / 1000, 'unixepoch') AS ended,
       exact_lat, exact_lon
FROM deployment_exact
ORDER BY entryStartDateTime;
```

The times are in UTC, and `ended` is empty for a deployment that is still running. A place has one exact point, so this covers every place the device has been at, past ones included, and not only the one in use.

The table holds the places the device has been at that have a location. A planned place is never in it, and neither is a place the database doesn't name. The view's `exact_lat` and `exact_lon` are empty for:

- A place with no location.
- A place the control app no longer has, because you deleted it.
- A deployment from [before any place was recorded](#the-location-page), which names no place.

A [correction](#correct-a-wrong-location-or-bearing) shows in the copy as corrected: the place has one point, and a corrected place has the new one, with its rows' rounded location corrected the same way. A copy you downloaded earlier keeps the values it had, so two copies of the same device can differ, and the newer one is right. The copy doesn't hold the record of corrections.

The database on the device is unchanged: it never holds the table or the view, and the **Download the database** button on the [Data export](https://docs.trafficmonitor.ai/dev/ui/database/#download-the-database) page still saves rounded locations only. The device removes its working copy when the download ends. The file you saved says where the device was, so give it only to people who should know. The table holds what the [`exact_location`](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/#the-exact-location-in-a-database-copy) attribute holds when you share the exact location.

## Choose the precision

**Precision**, at the end of the page, sets how much of the location the database stores. To better protect your privacy, it's rounded to about 1 km by default. The choices stay closed until you open **Change the precision**, which also shows the current choice, because most devices never need to change it. The setting is for the whole device, not for one place. Each choice shows how the same point would be stored:

| Choice                                       | The database stores                      |
| -------------------------------------------- | ---------------------------------------- |
| **No location stored**                       | No coordinates                           |
| **About 10 km** (45.5, -122.7)               | One decimal place, about a city          |
| **About 1 km** (45.52, -122.69), the default | Two decimal places, about a neighborhood |

The exact location is never stored in the database. It stays on this device, and leaves it only if you [share it](https://docs.trafficmonitor.ai/dev/use/sharing/index.md), [export it](#export-the-exact-locations), [download a copy of the database that holds it](#download-the-database-with-exact-locations), or save it with a camera's [reference picture](https://docs.trafficmonitor.ai/dev/use/cameras/#take-a-reference-picture). Choose one and **Save**.

- **A coarser choice** applies to the deployments running now at once. Rows stored before them keep their precision unless you tick **Also round the rows already stored**, which asks first, because it can't be undone.
- **No location stored** removes the stored location from the deployments running now at once. Tick **Also remove it from the rows already stored** to remove it from every row in the database as well, which also asks first. The exact location stays on the device, but the database can't get the rounded values back.
- **A finer choice** applies from the next deployment. Rows already stored stay as they are, because what was rounded away can't come back.

## What leaves the device

- A place's description, and the reasons you give for corrections, never leave the device.
- A copy of the database holds the place's id and its location at the stored precision: about a neighborhood at about 1 km, or about a city at about 10 km. The exact location isn't in it, unless you made the copy with [**Download the database with exact locations**](#download-the-database-with-exact-locations), which adds each place's exact location in a table of its own.
- Data you [share](https://docs.trafficmonitor.ai/dev/use/sharing/index.md) carries the location as the database stores it. The exact location goes only if you tick **Share the exact location**, and only for the place in use. The file from [**Export exact locations**](#export-the-exact-locations), and the copy from [**Download the database with exact locations**](#download-the-database-with-exact-locations), go where you send them.
- A camera's [reference picture](https://docs.trafficmonitor.ai/dev/use/cameras/#take-a-reference-picture) holds the exact location of the place in use unless you clear **Include this place's exact location**, and the pictures show the street. The zip goes where you send it.
- A correction or a coarser precision changes the device's own records only. Copies of the database already downloaded, and data already uploaded, keep the values they had.

To change these values in `config.yml` by hand, see [Edit the location by hand](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#edit-the-location-by-hand).
