# Assembly

These steps assume the [parts list](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/recommended-hardware/index.md) and the 3D-printed enclosure. Each numbered step matches a numbered photo.

Full set of Traffic Monitor parts ready for assembly

Steps 1 to 34 assemble the Raspberry Pi 5, Camera Module 3, AI accelerator (Coral TPU HAT or AI HAT+), and radar. Steps 35 to 51 add the optional air quality sensor.

## Core parts

1. Lay out all your parts and screws
1. Lay out all your parts and screws (double-check)
1. M3×12 mm screws for the camera, M3×6 mm for the radar, M3×10 mm for the carrier board
1. Lay out all your parts and screws
1. (Coral TPU M.2 module and HAT pictured) Unbox the AI accelerator and the M.2 board, if separate
1. (Coral TPU M.2 module and HAT pictured) Attach the M.2 module to the board and attach the ribbon cable
1. Attach the active cooler to the Raspberry Pi
1. Lay out the HAT stand-offs
1. Attach the stand-offs to the board (bottom-HAT version shown)
1. Plug in the PCIe ribbon cable. *Match the triangle marks on the ribbon cable, the Raspberry Pi, and the HAT.*
1. Attach the HAT to the Raspberry Pi (bottom HAT shown, for the Coral TPU)
1. Locate the Raspberry Pi carrier plate
1. Turn the carrier plate so the built-in stand-offs point down
1. Mount the Raspberry Pi and HAT to the carrier plate
1. Bottom of the carrier plate
1. Locate the radar and its mounting board
1. Attach the radar to the mounting board with M3×6 mm screws, with the antenna (the white and gold areas) at the bottom and the micro-USB plug near the camera cut-out
1. Locate the camera, camera mounts, and camera ribbon cable
1. If the camera came with a white ribbon cable, remove it. It doesn't fit the Raspberry Pi 5.
1. Attach the Raspberry Pi 5 camera ribbon cable to the camera
1. Slide the camera into the first camera mounting plate
1. Snap on the other camera mounting plate so all the holes and pins align
1. The camera mount stand-offs are on the back, and the first plate sits flush with the end of the stand-offs
1. Locate the main mounting board and the assembled camera mount
1. Locate four M3×12 mm screws for the camera
1. (Pictures continue below) Mount the camera in either of the camera mount holes
1. Radar and camera mounted, from the front
1. Pass the camera ribbon cable through the camera mounting hole to the back
1. Front view with the camera ribbon cable through the back
1. Locate the main mounting board, the carrier plate, and the M3×10 mm screws
1. Attach the carrier board to the main board
1. Front view with the carrier board attached
1. Plug the camera ribbon cable into either of the Raspberry Pi 5 camera connectors
1. Place the main mounting board into the enclosure, with the radar and camera at the top facing forward, and secure it with M3×10 mm screws in the four corners

## Air quality sensor

35. Locate the Enviro+ board and the particulate matter (PM) sensor
01. Unpack both
01. Attach the Enviro+ board to the PM sensor
01. Back of the Enviro+ board
01. Locate the GPIO ribbon cable
01. Attach the ribbon cable to the Enviro+ board with the wires going down and the notch on top
01. Place the PM sensor in its slot, pushed fully onto the pins in the bottom of the enclosure
01. The PM sensor from below
01. Slip the Enviro+ board into the air quality carrier board
01. Line up the pins on the bottom of the carrier board with the Enviro+ board. It may be snug.
01. Gently place the carrier board into the alignment slots in the enclosure
01. There should be almost no gap between the carrier board and the enclosure
01. Fold the ribbon cable up and tuck the PM sensor cable on top of the PM sensor
01. Slide the air quality shroud into its slots so you can see the screw inserts, and secure it with M3×8 mm screws
01. Front of the assembled sensor
01. Top of the assembled sensor
01. The assembled sensor from outside the enclosure

### Attach the GPIO ribbon cable

Attach the ribbon cable to the Raspberry Pi's GPIO pins with the notch on top.

Attach the ribbon cable with the notch toward the outside of the Raspberry Pi

- Pre-fold the cable so it lies flat when the case is closed.
- The connector is tight on the pins and close to the cooler's heatsink. Work it down a few millimeters at a time, side to side, until it's fully seated.
- To remove it, unplug the Raspberry Pi first. Slide a flat-head screwdriver between the connector and the plastic header and work the connector off a few millimeters at a time, taking care not to short the pins.

## Ready to deploy

Close the case. Next, [install the software](https://docs.trafficmonitor.ai/dev/software-installation/index.md).

Traffic Monitors ready to count
