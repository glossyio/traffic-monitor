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
* [ ] Enclosure:  [Traffic Monitor Enclosure 3D Print Model](https://github.com/greendormer/tm-enclosure-3d)

## Computing Device

(Required) [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB

{% hint style="warning" %}
The Raspberry Pi 4B and earlier units are not recommended as they have experienced detrimental performance due to not meeting the power requirements on the peripherals (USB) for the TPU and radar for this setup.
{% endhint %}

### Storage

(Required) A high-quality microSD card. Recommend at least 32GB capacity for system files with minimal (or no) snapshot and video capture. Recommend purchasing a high performance card, even when configuring for minimal recording.&#x20;

* Setup has been tested and works well with the [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA).
* [Raspberry Pi official SD Card](https://www.raspberrypi.com/products/sd-cards/?variant=sd-64gb) should perform particularly well, but sizes only range up to 128GB.
* There are many options on the RPi5 to use a faster, more durable NVME (M.2) drive, including those that pair with the Coral TPU, such as the Pineboards [HatDrive AI! Coral TPU bundle](https://pineboards.io/products/hatdrive-ai-coral-edge-tpu-bundle-nvme-2230-2242-gen-2-for-raspberry-pi-5).

### Power&#x20;

(Recommended) The official [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/) for testing and permanent mounts.

Although the Raspberry Pi 5 is rated for 27-watts (5V at 5A) and less power will often cause resets or throttling,the Traffic Monitor typically consumes between 6-14-watts of energy  when it is fully operational and inferencing, depending on number of components in use and how much motion is detected.

## Camera(s)

(Required) [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) or [Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for object detection (requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is not included).

The Raspberry Pi 5 has 2 camera transceiver slots, so you can easily attach 2 native Raspberry Pi cameras to the board. In fact, any camera that can output H.264 is conceivably compatible with the traffic monitor, so you may attach USB or even networked cameras. See more at [Frigate's recommended camera hardware](https://docs.frigate.video/frigate/hardware#cameras). &#x20;

{% hint style="info" %}
See the [Frigate camera setup](https://docs.frigate.video/frigate/camera_setup) for more information on tuning stream configurations based on various goals for your deployment.
{% endhint %}

## AI Co-processor (TPU)

(Required with camera) [Coral AI Tensor Processing Unit (TPU)](https://coral.ai/products/). The Coral TPU is capable of 100+ FPS with millisecond inference time. Other co-processors may work, but the Coral TPU is fully supported with [Frigate object detectors](https://docs.frigate.video/configuration/object_detectors) out of the box. &#x20;

* [Coral USB Accelerator](https://coral.ai/products/accelerator) is easy-to-use co-processor that you can connect to any computing device with a USB interface.
* Pineboards offers the [Hat AI! Coral TPU bundle](https://pineboards.io/products/hat-ai-coral-edge-tpu-bundle-for-raspberry-pi-5) that connects via PCIe that offers a sleek way to add the Coral capabilities.

## Radar

(Recommended) [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - provides accurate radar-based speed/direction detection.

## Other Sensors

(Optional) Air Quality sensor ([Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/)) with [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/).

## Enclosure

External enclosure and internal mounting board are available as 3D models at the open source repo [greendormer/tm-enclosure-3d](https://github.com/greendormer/tm-enclosure-3d).  See [enclosure-3d-print.md](build-your-own-device-diy/enclosure-3d-print.md "mention")section for more details.
