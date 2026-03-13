---
description: Is it possible to do this...
---

# Use Cases and Scenarios

We are only as powerful as the story we tell.  What can we do with the data we collect?  What can the traffic monitor do?

The TrafficMonitor.ai collects an extensive amount of data, depending on the sensors installed. For details on payloads, check out [events-payload.md](../data-and-payloads/events-payload.md "mention"), [radar-payload.md](../data-and-payloads/radar-payload.md "mention"), and [air-quality-aq-payload.md](../data-and-payloads/air-quality-aq-payload.md "mention").

## How can I perform a "near miss" analysis using this hardware?

This scenario is where there is a driver of a vehicle and a vulnerable road user like a pedestrian at the crosswalk at the same time.

This is an important and dangerous situation that has absolutely been largely un-captured in our current transportation system. **We need to create definitions on what a "near miss / near hit" is**, but we have laws we can follow for this. [PortlandBicycleSchool.com](https://portlandbicycleschool.com/driving-around-bicycles/driving-around-pedestrians-faq/) highlights many of these:

* In Oregon, _every corner is a crosswalk_. ORS 801.220
* Pedestrians invoke their right to cross when any part or extension of the pedestrian (body, cane, wheelchair, or bicycle) enters the crosswalk. ORS 811.028(4), 814.040(1)(a)
* A driver must remain stopped Until the pedestrian passes the driver’s lane (or lane they intend to turn into) plus one further lane. ORS 811.028

To accomplish this with the TrafficMonitor, the following would allow for analysis of events that have a driver / pedestrian conflict:

1. Mount a TM watching an intersection.
2. Draw zones that represent "pedestrian zones" and "driver zones".
3. This will create separate events for `person` and `car` with relevant [event payload fields](https://docs.trafficmonitor.ai/sensor-payloads/events-payload) including `start_time`, `end_time`, and `entered_zones`.
4. Watch for events where a driver enters the zone simultaneously as a pedestrian in their zone (overlapping start/end times) where the zones will be in conflict.
5. Download the data and create an analysis that looks at those potential conflicts.

Example scenario analysis:

* if a person was at the `zone_ped_ne` (bottom left) and wanted to cross S or W
* and a car simultaneously entered the `zone_intersection_e` (left) and wanted to turn into `zone_intersection_n`(right)
* and the car \_turned first\_ into the `zone_intersection_n` before the pedestrian crossed, based on `start_time` and `end_time` for both events
* This would potentially be a "near miss" or at least an illegal maneuver for a driver while a pedestrian was in the crosswalk.

You can potentially add in other elements to make the requires more stringent, like seeing if the car was stationary at the stop sign or just blew through it. Or tighten the "pedestrian zone" to represent the very edges of the sidewalk to show the pedestrian had "intent to cross".

<figure><img src="../.gitbook/assets/Screenshot_20250620_114712.png" alt=""><figcaption><p>Example of a potential near-miss scenario zone tracking set up.  Zones everywhere!</p></figcaption></figure>

Of course, the truly more harrowing observations would include those where a `person` and `car` were in the same `zone_intersection` (on the road) at the same time. That would obviously be a "near miss" if it wasn't a true driver striking a pedestrian.

## How can I capture a vehicle not stopping at a stop sign?

This is an all-too-common scenario where a vehicle does not come to a complete stop and/or stop for the legally-mandated amount of time before proceeding through a stop sign. This is also referred to as a "[rolling stop](https://en.wikipedia.org/wiki/Stop_sign#Compliance_requirements)", Rhode Island stop, or California stop, depending where you live.

{% hint style="info" %}
If you are a stickler for the law and want to capture all modalities, be aware that _bicyclists may apply the stop-as-yield_ in some jurisdictions, see [Idaho stop](https://en.wikipedia.org/wiki/Idaho_stop).
{% endhint %}

This is easy to set up to capture this scenario in Frigate. &#x20;

1. Set up the Traffic Monitor.  The ideal location for a camera is high looking down at the entire intersection.
2. Set up your Frigate zones:
   1. Set up a "stop sign zone" in a **thin strip in front of your stop signs**, in the example below you will see `zone_stop_sign_e` and `zone_stop_sign_w` for the 2-way stop on the east and west, respectively.  \
      ![](../.gitbook/assets/Screenshot_20260313_111755.png)
   2. For the newly created stop sign zone, set up a "[Loitering Time](https://docs.frigate.video/configuration/zones/#zone-loitering)" that aligns with your jurisdiction's rules; e.g. 3-seconds and optionally limit it only to `cars` object. This will cause that zone to only appear if the vehicle is stationary for that amount of time, otherwise the zone will not appear in the object's `entered_zones` payload.\
      ![](../.gitbook/assets/Screenshot_20260313_112908.png)
   3. Optionally set up wider zones for each intersection so you can also do analysis on turning behavior.  You will be able to calculate, for example, if a car went from the `zone_intersection_e`  to `zone_intersection_n` , which is a right turn! You may find some interesting driver behaviors.\
      ![](../.gitbook/assets/Screenshot_20260313_113029.png)<br>
3. Confirm your zone placements by observing a few instances. Click on the _Frigate > Explore panel,_ and look for `car` objects that wen through your zone.  It may take a long time to find a car that appropriately does the stop.\
   ![](../.gitbook/assets/Screenshot_20260313_121735.png)
