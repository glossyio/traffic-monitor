---
description: Commodity hardware to enable object detection and speed/direction measurement.
---

# Recommended Hardware

Customize the hardware to fit your needs!  The core components include the computing device, storage, camera, and co-processor. Feel free to mix-and-match components but most of the documentation and default configuration assumes using the hardware recommended below.

{% hint style="info" %}
We are not affiliated with any of the stores or companies linked in this section. These are suggestions that have been used or tested by contributors. If you have used or tested more, post on [TM GitHub discussions](https://github.com/glossyio/traffic-monitor/discussions)!
{% endhint %}

## Hardware Check List

Use the following checklist as a quick guide to components you need to purchase

* [ ] Computing Device:   [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB
* [ ] Storage: microSD card (≥32GB), [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA)
* [ ] Power: official RPi [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/)
* [ ] Camera: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) plus [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/)
* [ ] AI co-processor: [Coral AI Tensor Processing Unit (TPU)](https://coral.ai/products/)
* [ ] Radar (optional): [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/)
* [ ] Enclosure:  [#enclosure-weather-resistant-box](recommended-hardware.md#enclosure-weather-resistant-box "mention")

## Computing Device

(Required) [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB. The Traffic Monitor is designed around 4GB memory profile, but if you have many sensors and other applications running, 8GB may be more performant.

{% hint style="warning" %}
The Traffic Monitor is based on the Raspberry Pi 5. The Raspberry Pi 4B and earlier units are not recommended as they have experienced detrimental performance due to not meeting the power requirements on the peripherals (USB) for the TPU and radar for this setup.  However, many have been successful with earlier versions of the Raspberry Pi for object detection, so your mile may vary.
{% endhint %}

### Storage

(Required) A high-quality microSD card or a SSD (see alternative). Recommend at least 32GB capacity for system files with minimal (or no) snapshot and video capture.

1. _Option_: Setup has been tested and works well with the [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA).
2. _Option_: [Raspberry Pi official SD Card](https://www.raspberrypi.com/products/sd-cards/?variant=sd-64gb) should perform particularly well but sizes only range up to 128GB.
3. _Alternative_: There are many options on the RPi5 to use a faster, more durable NVME (M.2) drive, including those that pair with the Coral TPU, such as the Pineboards [HatDrive AI! Coral TPU bundle](https://pineboards.io/products/hatdrive-ai-coral-edge-tpu-bundle-nvme-2230-2242-gen-2-for-raspberry-pi-5).

### Power&#x20;

(Required) To run the Traffic Monitor and components.

{% hint style="warning" %}
The Raspberry Pi 5 is rated for 27-watts (5V at 5A) and using anything with a lower rating like the older RPi PSUs will often result in resets and/or throttling. However, the Traffic Monitor typically consumes between 6-14-watts of energy  when it is fully operational and inferencing, depending on number of components in use and how much motion is detected.
{% endhint %}

1. _Recommended Option_: The official [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/) for testing and permanent mounts.
2. _Alternative_: PoE (Power over Ethernet) HATs available for the RPi 5. Raspberry Pi Foundation has not yet released an official one, but if you have a working solution suggest it in the [TM GitHub Discussion](https://github.com/glossyio/traffic-monitor/discussions/new/choose)!

## Camera(s)

(Required) The official, connected Raspberry Pi cameras are below recommended for compact, local object detection; however any camera that can output H.264 is conceivably compatible with the traffic monitor, so you may attach USB or even networked cameras. See more at [Frigate's recommended camera hardware](https://docs.frigate.video/frigate/hardware#cameras) for alternatives. &#x20;

1. _Recommended Option_: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) (requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is not included).
2. _Alternative/additional:_ [Raspberry Pi Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for faster motion capture and custom-lens based on your needs (requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is not included).

The Raspberry Pi 5 has 2 camera transceiver slots, so you can easily attach 2 native Raspberry Pi cameras to the board.&#x20;

{% hint style="info" %}
See the [Frigate camera setup](https://docs.frigate.video/frigate/camera_setup) for more information on tuning stream configurations based on various goals for your deployment.
{% endhint %}

## AI Co-processor (TPU)

(Required with camera) [Coral AI Tensor Processing Unit (TPU)](https://coral.ai/products/). The Coral TPU is capable of 100+ FPS with millisecond inference time. Other co-processors may work, but the Coral TPU is fully supported with [Frigate object detectors](https://docs.frigate.video/configuration/object_detectors) out of the box. &#x20;

1. _Easiest Option_: [Coral USB Accelerator](https://coral.ai/products/accelerator) is easy-to-use co-processor that you can connect to any computing device with a USB interface.
2. _Alternative_: HATs (Hardware-Attached-on-Top \[of a Raspberry Pi]) are more compact, upgradable, and usually cheaper:
   * [Rapsberry Pi M.2 HAT+](https://www.raspberrypi.com/products/m2-hat-plus/) pairs nicely with the [Coral M.2 Accelerator A+E Key](https://coral.ai/products/m2-accelerator-ae).
   * Pineboards offers the [Hat AI! Coral TPU bundle](https://pineboards.io/products/hat-ai-coral-edge-tpu-bundle-for-raspberry-pi-5) that connects via PCIe that offers a sleek way to add the Coral capabilities with an additional slot for an M.2 SSD.

## Radar

(Recommended) [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - provides accurate radar-based speed/direction detection up to 100-meters away.  _Planned future capability_ of object detection with the radar, which will be enabled with a software update.

## Other Sensors

(Optional) Air Quality sensor, [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/), with [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/).

## Enclosure (weather-resistant box)

* _Purchase_: _(coming soon)_ Purchase the box or a kit to assemble yourself.&#x20;
* _Print it yourself_:  We offer a 3D printable model so you can build the truly open source Traffic Monitor.  Visit our open source repository [greendormer/tm-enclosure-3d](https://github.com/greendormer/tm-enclosure-3d) for details and parts list.
* _Alternative DIY_: There are many waterproof electrical junction boxes that may be modified to fit your needs with the traffic monitor. Rough dimensions to fit the Traffic Monitor components including the camera and radar should be around 9"x7"x4" such as the [TICONN IP67 ABS Enclosure](https://www.amazon.com/gp/product/B0B87X944Z).
