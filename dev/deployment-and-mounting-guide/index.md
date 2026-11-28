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

## Usual mounts

Three mounts cover most sites. When you record how the unit is mounted on the control app's [Mounting page](https://docs.trafficmonitor.ai/dev/use/location/#record-how-the-unit-is-mounted), picking one fills in its height and tilt as a starting point. Measure your own mount and correct the numbers afterwards.

| Mount                                | Height         | Tilt below level |
| ------------------------------------ | -------------- | ---------------- |
| Tripod beside the road               | 7 ft (2.13 m)  | 15°              |
| Pole or sign post                    | 12 ft (3.66 m) | 15°              |
| Upstairs window over an intersection | 16 ft (4.88 m) | 15°              |

- **Tripod beside the road** is the temporary setup above: a tripod raised to about 7 feet, with the camera looking down the road.
- **Pole or sign post** is a long-term mount on a post or pole you have permission to use, high enough to stay out of reach.
- **Upstairs window over an intersection** is a view from inside a building, above the street, looking down at the crossing.

A tilt of 0 is level and 90 is straight down. The tilt of 15 degrees is a starting point for all three, and the height is from the road surface to the lens.

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

- Aim the device so that traffic moves toward or away from it at **45 degrees or less**, and as shallow as the site allows. The [OmniPreSense field-of-view calculator](https://omnipresense.com/ops243-field-of-view-calculator/) shows how the angle affects the reading. A shallower angle is better for three reasons, which you can check with the calculator:
  - At 45 degrees a vehicle spends about a fifth of the time in the beam that it does at 20 degrees, so the radar takes far fewer readings of each pass.
  - The readings of one pass spread about three times as far, because the speed the radar reports changes faster as the vehicle moves across the beam.
  - Each 5 degrees you misjudge the angle changes the corrected speed by about 9 percent at 45 degrees, and by about 3 percent at 20.
- The radar can't tell one street from the other where two streets cross. A vehicle on the crossing street can send readings that fall in the time window of an event on the street you count, and a vehicle that turns changes its angle to the beam as it goes, so no one correction suits it. Point the unit along one street, and see [At an intersection](https://docs.trafficmonitor.ai/dev/setup-guide/#at-an-intersection) for how to draw the zones.
- The radar labels movement **inbound** (toward the device) and **outbound** (away from it), and the camera uses the same words. Place the device so those directions make sense for your roadway, for example inbound for downhill traffic.
- To find the radar's coverage, have someone hold the radar outside the case and watch the red and blue LEDs on its front as people and vehicles pass. Where the LEDs blink is where to draw `zone_radar`.

## Next steps

Plug the device in. It starts by itself, and the green LED on the Raspberry Pi shows it has power. Continue with [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).
