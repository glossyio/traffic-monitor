---
description: Commodity hardware to enable object detection and speed/direction measurement.
---

# Recommended Hardware

Customize the hardware to fit your needs!  The core components include the computing device, storage, camera, and co-processor. Feel free to mix-and-match components but most of the documentation and default configuration assumes using the hardware recommended below.

## Sample Configurations

Here are some sample sensor configurations and the data it collects:

* The **camera + AI co-processor** is the lowest cost and will give you object detection and direction.
* Add in a **radar** for the most accurate speed and direction measurements.
* Include an **environmental sensor** to also measure air quality, gases, particulate matter, noise, temperature, and much more.
* (_future feature_) Install **only the radar** for the most privacy-conscious built that will be capable of basic object detection, speed, and direction.
* Add in an additional camera to monitor a second direction using the same AI co-processor.\*\*

\*\* The traffic monitor software is capable of supporting potentially any number of cameras either connected directly or via a local feed on the same AI co-processor for monitor multiple directions or any other configuration (see [recommended hardware > cameras](https://docs.trafficmonitor.ai/build-your-own-device-diy/recommended-hardware#camera-s) for more details). The TM software also has support for up to four (4) radars directly connected and paired in any pattern to the cameras.&#x20;

## Hardware Check List - Bill of Materials (BOM)

Use the following checklist as a quick guide to components you need to purchase

{% hint style="info" %}
We are not affiliated with any of the stores or companies linked in this section. These are suggestions that have been used or tested by contributors. If you have used or tested more, post on [TM GitHub discussions](https://github.com/glossyio/traffic-monitor/discussions)!
{% endhint %}

* [ ] Computing Device:   [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB
  * [ ] Power: official RPi [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/)
  * [ ] (Recommended) CPU Cooler: [RPi5 active cooler](https://www.raspberrypi.com/products/active-cooler/)
* [ ] Storage: microSD card (≥32GB), [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA)
* [ ] Camera: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/)&#x20;
  * [ ] plus the [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/)
* [ ] AI co-processor: see [#ai-co-processor](recommended-hardware.md#ai-co-processor "mention") for options
* [ ] (Recommended) Radar: [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/)
* [ ] Enclosure: See [#enclosure-weather-resistant-box](recommended-hardware.md#enclosure-weather-resistant-box "mention") for options
* [ ] (Optional) Air quality (AQ) sensor: [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/) with [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/)
  * [ ] AQ sensor will need a [male-to-female GPIO ribbon cable](https://www.pishop.us/product/male-to-female-gpio-ribbon-cable/) with the TM enclosure

## Computing Device

(Required) [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB. The Traffic Monitor is designed around 4GB memory profile, but if you have many sensors and other applications running, 8GB may be more performant.

Also pick up a (very cheap) official CPU cooler: [RPi5 active cooler](https://www.raspberrypi.com/products/active-cooler/) which helps prevent overheating on very hot days.

{% hint style="warning" %}
The Traffic Monitor is based on the Raspberry Pi 5. The Raspberry Pi 4B and earlier units are not recommended as they have experienced detrimental performance due to not meeting the power requirements on the peripherals (USB) for the TPU and radar for this setup.  However, many have been successful with earlier versions of the Raspberry Pi for object detection, so your mileage may vary.
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
3. _(Future discussion)_ Solar panel + battery. There have been working prototypes, with caveats. Discuss it in the [TM GitHub Discussion](https://github.com/glossyio/traffic-monitor/discussions/new/choose)!

## Camera(s)

(Required) For full object detection capabilties.

The official, connected Raspberry Pi cameras are below recommended for compact, local object detection; however any camera that can output H.264 is conceivably compatible with the traffic monitor, so you may attach USB or even networked cameras. See more at [Frigate's recommended camera hardware](https://docs.frigate.video/frigate/hardware#cameras) for alternatives. &#x20;

1. _Recommended_: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) (wide angle recommended)
   1. Requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is sold separately.
2. _Alternative/additional:_ [Raspberry Pi Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for faster motion capture and custom-lens based on your needs&#x20;
   1. Requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is sold separately.

The Raspberry Pi 5 has 2 camera transceiver slots, so you can easily attach 2 native Raspberry Pi cameras.&#x20;

{% hint style="info" %}
See the [Frigate camera setup](https://docs.frigate.video/frigate/camera_setup) for more information on tuning stream configurations based on various goals for your deployment.
{% endhint %}

## AI Co-processor

(Required with camera) The AI co-processor is an efficient way to run the object detection model, much more efficient than CPU-alone.

{% hint style="info" %}
The AI co-processor is used by Frigate to run the object detection model, see Frigate's [supported hardware](https://docs.frigate.video/configuration/object_detectors) for more options and details.
{% endhint %}

[Coral AI Tensor Processing Unit (TPU)](https://coral.ai/products/). The Coral TPU is capable of 100+ FPS with millisecond inference time. Other co-processors may work, but the Coral TPU is fully supported with [Frigate object detectors](https://docs.frigate.video/configuration/object_detectors) out of the box. &#x20;

1. _Easiest Option_: [Coral USB Accelerator](https://coral.ai/products/accelerator) is easy-to-use co-processor that you can connect to any computing device with a USB interface.
2. _Alternative_: Coral HATs (Hardware-Attached-on-Top \[of a Raspberry Pi]) are more compact, upgradable, and usually cheaper:
   * [Rapsberry Pi M.2 HAT+](https://www.raspberrypi.com/products/m2-hat-plus/) pairs nicely with the [Coral M.2 Accelerator B+M Key](https://coral.ai/products/m2-accelerator-bm/) (not the A+E key!).
   * Pineboards offers the [Hat AI! Coral TPU bundle](https://pineboards.io/products/hat-ai-coral-edge-tpu-bundle-for-raspberry-pi-5) that connects via PCIe that offers a sleek way to add the Coral capabilities with an additional slot for an M.2 SSD.
3. _Alternative (currently testing)_: [Raspberry Pi AI HAT+](https://www.raspberrypi.com/products/ai-hat/) with Hailo-8L offers high-performance, power-efficient processing.

## Radar

(Recommended) Provides accurate speed and direction measurement.

1. [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - certified with same tests as law enforcement speed radars.  Detection up to 100-meters away. &#x20;

_Planned future capability_ of object detection and confirmation with the radar, which will be enabled with a software update.

## Other Sensors

(Optional) For additional environmental data.

1. Air quality (AQ) sensor: [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/) paired with the (recommended) [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/).  Also pick up a longer ribbon cable, we recommend the [male-to-female GPIO ribbon cable](https://www.pishop.us/product/male-to-female-gpio-ribbon-cable/).&#x20;

The TM enclosure attempts to isolate the AQ sensor by physically separating the hardware. This way the heat from the RPi and other components do not interfere with environmental readings.

{% hint style="info" %}
Get AQ sensor details and capabilities on the [air-quality-aq-payload.md](sensor-payloads/air-quality-aq-payload.md "mention") page.
{% endhint %}

## Enclosure (weather-resistant box)

* _Print it yourself_:  We offer a 3D printable model so you can build the truly open source Traffic Monitor.  Visit our open source repository [greendormer/tm-enclosure-3d](https://github.com/greendormer/tm-enclosure-3d) for details and parts list.
* _Purchase_: _(coming soon)_ Purchase the box or a kit to assemble yourself.&#x20;
* _Alternative DIY_: There are many waterproof electrical junction boxes that may be modified to fit your needs with the traffic monitor. Rough dimensions to fit the Traffic Monitor components including the camera and radar should be around 9"x7"x4" such as the [TICONN IP67 ABS Enclosure](https://www.amazon.com/gp/product/B0B87X944Z).
