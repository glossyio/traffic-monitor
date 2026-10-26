---
description: Where and how to mount a Traffic Monitor, for a few hours or for years, so the camera and radar get a clear view.
---

# Choose a site and mount

Deployment covers where the device goes, how it's mounted, and the angle of the camera and radar to the roadway. The zones and location are set afterwards in [First-time setup](setup-guide.md).

!!! danger

    **Follow the law.** Comply with all applicable laws and local regulations when installing, mounting, and deploying a Traffic Monitor, particularly in public spaces. Unauthorized surveillance can lead to legal consequences and infringe privacy rights. Consult legal professionals or local authorities if you are unsure of the requirements. This guide is for educational purposes; you are responsible for complying with the law and for the consequences of deploying and using the device.

    Mount the device only where you have permission, and don't attach it to utility poles without proper authorization.

## Mounting options

Choose a mount that lets you make fine adjustments, because the radar's angle and position need tuning on site.

The open source, 3D-printed [enclosure](build-your-own-device-diy/recommended-hardware.md#enclosure) has several mounting methods built in, depending on the variant:

* 1/4"-20 screw insert on the bottom and back, for camera and trail-camera mounting hardware
* VESA-compatible holes (75 and 100 mm)
* Arca-Swiss-compatible quick-release plate on the bottom, for tripods
* Strap slots on the back, for posts, poles, and trees
* Safety tether hole for a carabiner and strap

<div class="grid" markdown>

<figure markdown="span">
  ![Back of the enclosure showing VESA holes, a screw insert, strap slots, and a tether hole](assets/images/Screenshot_20260217_180711.png)
  <figcaption>Back: VESA holes, 1/4"-20 screw insert, strap slots, and safety tether hole (lower left)</figcaption>
</figure>

<figure markdown="span">
  ![Bottom of the enclosure showing the Arca-Swiss plate and a screw insert](assets/images/Screenshot_20260217_180444.png)
  <figcaption>Bottom: Arca-Swiss quick-release plate and 1/4"-20 screw insert</figcaption>
</figure>

</div>

## Temporary deployments

For counts over a few hours, such as an event or a point-in-time study, mount the device at or above head height with an unobstructed view of the roadway. A sturdy tripod and a compact portable power station work well.

<div class="grid" markdown>

<figure markdown="span">
  ![Traffic Monitor on a tall telescoping tripod beside an event route](assets/images/tripod-002.webp)
  <figcaption>On a 16-foot telescoping tripod, counting event participants</figcaption>
</figure>

<figure markdown="span">
  ![Researcher with a clipboard next to a Traffic Monitor on a camera tripod and a portable power station](assets/images/tripod-001.webp)
  <figcaption>Recording manual confirmation counts, with the device on a camera tripod and a portable power station</figcaption>
</figure>

</div>

## Permanent deployments

!!! warning

    **Work safely.** Use proper safety equipment and ladder practice. Make sure the device is securely mounted, all fasteners are tight, the safety tether is in place, and the mount is stable. Failure to do so can cause injury or property damage.

Long-term deployments work anywhere the camera has a good view of the roadway and the radar can be aimed along it: garage roofs, a wood post in a cement-filled bucket, a stone pillar. Keep the device out of reach and clear of anything that might grow or be parked in front of it.

<figure markdown="span">
  ![Two Traffic Monitors mounted on a private rooftop edge and a gate post](assets/images/permanent-mount-010.webp)
  <figcaption>Long-term deployments, with permission, on a private rooftop and a gate entrance</figcaption>
</figure>

## Best practices

* Mount the device above the roadway and out of reach, about 10 to 12 feet up, for the best view and the least tampering.
* Choose a clear view of the road. Objects are still tracked when they pass briefly behind a tree or lamp post.
* Keep the radar off parking spots and other places where vehicles stop, because stationary vehicles get in the way of its readings.
* The camera detects objects anywhere in its field of view, so frame the whole stretch of road you care about.
* Think about which [zones](setup-guide.md#3-adjust-the-zones) your use case needs, and whether the view lets you draw them.

### Sample deployments

<div class="grid" markdown>

<figure markdown="span">
  ![Camera view down a quiet residential street](assets/images/deployment-rvc-2025-07.webp)
  <figcaption>Quiet road, monitoring downhill movement</figcaption>
</figure>

<figure markdown="span">
  ![Camera view of a wide commercial street with traffic coming toward the camera](assets/images/deployment-cookies-2025-07.webp)
  <figcaption>Busy business district, nearly head-on movement on a wide road</figcaption>
</figure>

<figure markdown="span">
  ![Camera view across a commercial street with a crosswalk in the foreground](assets/images/deployment-next_adventure-2025-07.webp)
  <figcaption>Busy business district, side-on view focused on a pedestrian and bike crosswalk</figcaption>
</figure>

</div>

<div class="grid" markdown>

<figure markdown="span">
  ![Tree-lined neighborhood greenway with a bike lane](assets/images/location-001.jpeg)
  <figcaption>Neighborhood greenway, an ideal spot to count bikes, pedestrians, and cars</figcaption>
</figure>

<figure markdown="span">
  ![Mounting spot on a greenway, looking south](assets/images/location-003.jpeg)
  <figcaption>Greenway mounting spot, facing south</figcaption>
</figure>

<figure markdown="span">
  ![Mounting spot on a greenway, looking north](assets/images/location-002.jpeg)
  <figcaption>Greenway mounting spot, facing north</figcaption>
</figure>

</div>

### Camera considerations

The camera detects objects anywhere in the frame, so cover the whole area of interest even if the roadway isn't centered. An unobstructed view gives the best results.

<figure markdown="span">
  ![Frigate debug view with detection boxes around several objects across the frame](assets/images/image.png)
  <figcaption>Detections can happen anywhere in the camera's field of view</figcaption>
</figure>

### Radar considerations

The radar has a narrower field of view than the camera and measures speed accurately only at a shallow angle to the direction of travel.

* Aim the device so that traffic moves toward or away from it at **45 degrees or less**. The [OmniPreSense field-of-view calculator](https://omnipresense.com/ops243-field-of-view-calculator/) shows how the angle affects the reading.
* The radar labels movement **inbound** (toward the device) and **outbound** (away from it), and the camera uses the same words. Place the device so those directions make sense for your roadway, for example inbound for downhill traffic.
* To find the radar's coverage, have someone hold the radar outside the case and watch the red and blue LEDs on its front as people and vehicles pass. Where the LEDs blink is where to draw `zone_radar`.

## Next steps

Plug the device in. It starts by itself, and the green LED on the Raspberry Pi shows it has power. Continue with [First-time setup](setup-guide.md).
