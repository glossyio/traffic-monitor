# Choose a site and mount

Deployment covers where the device goes, how it's mounted, and the angle of the camera and radar to the roadway. The zones and location are set afterwards in [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).

Danger

**Follow the law.** Comply with all applicable laws and local regulations when installing, mounting, and deploying a Traffic Monitor, particularly in public spaces. Unauthorized surveillance can lead to legal consequences and infringe privacy rights. Consult legal professionals or local authorities if you are unsure of the requirements. This guide is for educational purposes; you are responsible for complying with the law and for the consequences of deploying and using the device.

Mount the device only where you have permission, and don't attach it to utility poles without proper authorization.

## Mounting options

Choose a mount that lets you make fine adjustments, because the radar's angle and position need tuning on site.

The open source, 3D-printed [enclosure](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/recommended-hardware/#enclosure) has several mounting methods built in, depending on the variant:

- 1/4"-20 screw insert on the bottom and back, for camera and trail-camera mounting hardware
- VESA-compatible holes (75 and 100 mm)
- Arca-Swiss-compatible quick-release plate on the bottom, for tripods
- Strap slots on the back, for posts, poles, and trees
- Safety tether hole for a carabiner and strap

Back: VESA holes, 1/4"-20 screw insert, strap slots, and safety tether hole (lower left)

Bottom: Arca-Swiss quick-release plate and 1/4"-20 screw insert

## Temporary deployments

For counts over a few hours, such as an event or a point-in-time study, mount the device at or above head height with an unobstructed view of the roadway. A sturdy tripod and a compact portable power station work well.

On a 16-foot telescoping tripod, counting event participants

Recording manual confirmation counts, with the device on a camera tripod and a portable power station

## Permanent deployments

Warning

**Work safely.** Use proper safety equipment and ladder practice. Make sure the device is securely mounted, all fasteners are tight, the safety tether is in place, and the mount is stable. Failure to do so can cause injury or property damage.

Long-term deployments work anywhere the camera has a good view of the roadway and the radar can be aimed along it: garage roofs, a wood post in a cement-filled bucket, a stone pillar. Keep the device out of reach and clear of anything that might grow or be parked in front of it.

Long-term deployments, with permission, on a private rooftop and a gate entrance

## Best practices

- Mount the device above the roadway and out of reach, about 10 to 12 feet up, for the best view and the least tampering.
- Choose a clear view of the road. Objects are still tracked when they pass briefly behind a tree or lamp post.
- Keep the radar off parking spots and other places where vehicles stop, because stationary vehicles get in the way of its readings.
- The camera detects objects anywhere in its field of view, so frame the whole stretch of road you care about.
- Think about which [zones](https://docs.trafficmonitor.ai/dev/setup-guide/#3-adjust-the-zones) your use case needs, and whether the view lets you draw them.

### Sample deployments

Quiet road, monitoring downhill movement

Busy business district, nearly head-on movement on a wide road

Busy business district, side-on view focused on a pedestrian and bike crosswalk

Neighborhood greenway, an ideal spot to count bikes, pedestrians, and cars

Greenway mounting spot, facing south

Greenway mounting spot, facing north

### Camera considerations

The camera detects objects anywhere in the frame, so cover the whole area of interest even if the roadway isn't centered. An unobstructed view gives the best results.

Detections can happen anywhere in the camera's field of view

### Radar considerations

The radar has a narrower field of view than the camera and measures speed accurately only at a shallow angle to the direction of travel.

- Aim the device so that traffic moves toward or away from it at **45 degrees or less**. The [OmniPreSense field-of-view calculator](https://omnipresense.com/ops243-field-of-view-calculator/) shows how the angle affects the reading.
- The radar labels movement **inbound** (toward the device) and **outbound** (away from it), and the camera uses the same words. Place the device so those directions make sense for your roadway, for example inbound for downhill traffic.
- To find the radar's coverage, have someone hold the radar outside the case and watch the red and blue LEDs on its front as people and vehicles pass. Where the LEDs blink is where to draw `zone_radar`.

## Next steps

Plug the device in. It starts by itself, and the green LED on the Raspberry Pi shows it has power. Continue with [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).
