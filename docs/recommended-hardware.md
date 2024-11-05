---
description: >-
  The traffic monitor is built from commodity hardware to enable object
  detection and speed/direction measurement.
---

# Recommended Hardware

Customize the hardware to fit your needs.  The core components include the computing device, storage, camera, and co-processor.&#x20;

{% hint style="info" %}
We are not affiliated with any of the stores or companies linked in this section. These are suggestions that have been used or tested by contributors. If you have used or tested more, submit a PR to add them!
{% endhint %}

## Computing Device

(Required) [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB

{% hint style="warning" %}
The Raspberry Pi 4B and earlier units are not recommended as they have experienced detrimental performance due to not meeting the power requirements on the peripherals (USB) for the TPU and radar for this setup.
{% endhint %}

(Required) A high-quality microSD card (>= 32GB with minimal snapshot and video capture). Recommend a high performance card, even when configuring for minimal recording. Setup has been tested and works well with the [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA).

(Recommended) The official [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/) for testing and permanent mounts.

## Camera(s)

The Raspberry Pi 5 has 2 camera transceiver slots, so you can easily attach 2 native Raspberry Pi cameras to the board.&#x20;

In fact, any camera that can output H.264 is conceivably compatible with the traffic monitor, so you may also attach USB or even networked cameras for object detection. &#x20;

{% hint style="info" %}
See the [Frigate Camera setup](https://docs.frigate.video/frigate/camera\_setup) for more information on goals for tuning stream configurations for cameras.
{% endhint %}

(Required) [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) or [Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for object detection (requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/)).

## AI Co-processor (TPU)

(Required with camera) [Coral AI Tensor Processing Unit (TPU)](https://coral.ai/products/). The [Coral USB Accelerator](https://coral.ai/products/accelerator) is easy-to-use co-processor and capable of 100+ FPS with millisecond inference time. Other co-processors may work, but this is supported with [Frigate](https://github.com/blakeblackshear/frigate) for object detectionn.

## Radar

(Recommended) [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - provides accurate radar-based speed/direction detection.

## Other Sensors

(Optional) Air Quality sensor ([Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/)) with [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/).

## Enclosure

External enclosure and internal mounting board need to be custom made at the moment, instructions coming soon.
