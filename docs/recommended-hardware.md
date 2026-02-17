---
description: Commodity hardware to enable object detection and speed/direction measurement.
---

# Recommended Hardware

Customize the hardware to fit your needs!  The core components include the computing device, storage, camera, and co-processor. Feel free to mix-and-match components but most of the documentation and default configuration assumes using the hardware recommended below.

## Sample Configurations

Here are some sample sensor configurations and the data it collects:

1. **Camera + AI co-processor** is the lowest cost and will give you object detection, direction, visual speed measurements, and much more.
2. Add in a **radar** for the most accurate speed and direction measurements and basic object detection for nighttime detection.
3. Include an **environmental sensor** to also measure air quality, gases, particulate matter, noise, temperature, and much more.
4. (_future feature_) Install **only the radar** for the most privacy-conscious built that will be capable of basic object detection, speed, and direction.
5. Add additional camera(s) to monitor more directions using the same AI co-processor.\*\*

\*\* The traffic monitor software is capable of supporting potentially any number of cameras either connected directly or via a local feed on the same AI co-processor for monitor multiple directions or any other configuration (see [recommended hardware > cameras](https://docs.trafficmonitor.ai/build-your-own-device-diy/recommended-hardware#camera-s) for more details). The TM software also has support for up to four (4) radars directly connected and paired in any pattern to the cameras.&#x20;

## Hardware Check List - Bill of Materials (BOM)

Use the following checklist as a quick guide to components you need to purchase

{% hint style="info" %}
We are not affiliated with any of the stores or companies linked in this section. These are suggestions that have been used or tested by contributors. If you have used or tested more, post on [TM GitHub discussions](https://github.com/glossyio/traffic-monitor/discussions)!
{% endhint %}

* [ ] Computing Device:   [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB
  * [ ] Power: official RPi [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/)
  * [ ] (_Recommended_) CPU Cooler: [RPi5 active cooler](https://www.raspberrypi.com/products/active-cooler/)
* [ ] Storage: microSD card (≥32GB),&#x20;
  * [ ] [Raspberry Pi SD Cards](https://www.raspberrypi.com/products/sd-cards/) are modern, fast, stable microSD cards.
  * [ ] OR [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA) for larger sizes to store more videos and snapshots
* [ ] Camera: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/)&#x20;
  * [ ] plus the [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/)
* [ ] AI co-processor: see [#ai-co-processor](recommended-hardware.md#ai-co-processor "mention") for options
* [ ] (_Recommended_) Radar: [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/)
* [ ] Enclosure: See [#enclosure-weather-resistant-box](recommended-hardware.md#enclosure-weather-resistant-box "mention") for options
* [ ] (_Optional_) Air quality (AQ) sensor: [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/) with [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/)
  * [ ] AQ sensor will need a [male-to-female GPIO ribbon cable](https://www.pishop.us/product/male-to-female-gpio-ribbon-cable/) with the TM enclosure

## Computing Device

(_Required_) [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (RPi 5) 4GB/8GB. The Traffic Monitor is designed around 4GB memory profile, but if you have many sensors and other applications running, 8GB may be more performant.

Also pick up a (very cheap) official CPU cooler: [RPi5 active cooler](https://www.raspberrypi.com/products/active-cooler/) which helps prevent overheating on very hot days.

{% hint style="warning" %}
The Traffic Monitor is based on the Raspberry Pi 5. The Raspberry Pi 4B and earlier units are not recommended as they have experienced detrimental performance due to not meeting the power requirements on the peripherals (USB) for the TPU and radar for this setup.  However, many have been successful with earlier versions of the Raspberry Pi for object detection, so your mileage may vary.
{% endhint %}

### Storage

(_Required_) A high-quality microSD card or a SSD (see alternative). Recommend at least 32GB capacity for system files with minimal (or no) snapshot and video capture.

1. _Option_: Setup has been tested and works well with the [SanDisk Extreme Pro microSDXC UHS-I Card](https://www.westerndigital.com/products/memory-cards/sandisk-extreme-pro-uhs-i-microsd?sku=SDSQXCD-128G-GN6MA).
2. _Option_: [Raspberry Pi official SD Card](https://www.raspberrypi.com/products/sd-cards/?variant=sd-64gb) performs particularly well but sizes only range up to 128GB.
3. _Alternative_: There are many options on the RPi5 to use a faster, more durable NVME (M.2) drive, including those that pair with the Coral TPU or other AI co-processors.

### Power&#x20;

(Required) To run the Traffic Monitor and components.

{% hint style="warning" %}
The Raspberry Pi 5 is rated for 27-watts (5V at 5A) and using anything with a lower rating like the older RPi PSUs will result in resets and/or throttling. However, the Traffic Monitor typically consumes between 6-14-watts of energy  when it is fully operational and inferencing. All components are intended to be powered off the Raspberry Pi 5, so a quality power source is recommended.
{% endhint %}

1. _(Recommended)_ The official [27W USB-C Power Supply](https://www.pishop.us/product/raspberry-pi-27w-usb-c-power-supply-black-us/) for testing and permanent mounts.
2. _(Alternative)_ PoE (Power over Ethernet) HATs available for the RPi 5.&#x20;
   1. [Waveshare PoE HAT (F)](https://www.waveshare.com/poe-hat-f.htm) or [Waveshare PoE M.2 HAT+](https://www.waveshare.com/PoE-M.2-HAT-Plus.htm) has performed well for some contributors.
   2. You will need a PoE+ power supply, such as a [PoE+ Power Injector](https://www.raspberrypi.com/products/poe-plus-injector/).
3. (_Alternative_) Battery for off-grid.
   1. Required components:&#x20;
      1. [Buck converter](https://en.wikipedia.org/wiki/Buck_converter) (step-down converter) to step down a 12v (or 24v) battery to 5v@5A for the Raspberry Pi 5
      2. &#x20;[LFP](https://en.wikipedia.org/wiki/Lithium_iron_phosphate_battery) (LiFePO<sub>4</sub>) battery at 12v or 24v with Amp-hours (Ah) to last desired time frame.
   2. Sample battery calculation (YMMV[^1]): the TM consumes \~13-watts, running it for 24-hour will require 13\*24=312 Wh (Watt-hours), the LFP battery needs to be 312/12= 26, which would be 12-volts @ 30-Ah.
4. _(Prototypes)_ Solar panel + battery.&#x20;
   1. Components: Same as battery above plus [photovoltaic](https://en.wikipedia.org/wiki/Photovoltaics) (PV) panel and [solar charge controller](https://en.wikipedia.org/wiki/Charge_controller)
   2. Sample calculation:&#x20;
      1. Find your daily [Solar PV potential](https://profilesolar.com/countries/US/); e.g. Portland, OR has 7.15 and 1.42 kWh[^2]/day potential in an optimum summer and winter, respectively.
      2. Choose your PV panel size and calculate potential energy generation for the lowest time of year (winter in northern hemisphere).
         1. Potential \* Size of PV panel = production per day; e.g. 1.42 \* 0.1 (100-watt panel) = 142-Watts per day production in Portland, OR winter
      3. PWM solar controllers have \~80% efficiency on power conversion
         1. Production per day \* controller efficiency = 142\*0.8 = 113-Watts per day available.
      4. Calculate battery size requirements as above.&#x20;
      5. _Note_: **This is not enough to run the TM and charge a battery**. You would require 3-times that amount, closer to a 300-watt PV in a Portland, OR winter.
   3. (_Caveat)_ Solar production is very dependent on the amount of sun you are able to harvest. You need to consider factors like orientation/angle of panels, non-optimal days (cloudy, rainy), anything that blocks the sun such as trees, and more.
   4. Discuss more on the [TM GitHub Discussion](https://github.com/glossyio/traffic-monitor/discussions/new/choose)!

## Camera(s)

(Required) For full object detection capabilities.

{% hint style="info" %}
The official Raspberry Pi cameras are below recommended for low-cost, compact, local object detection; however any camera that can output H.264 is compatible with the traffic monitor, so you may attach USB or even networked cameras.  &#x20;
{% endhint %}

1. _(Recommended)_ [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/) (wide angle recommended)
   1. Requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is sold separately.
2. _(Alternative/additional)_ [Raspberry Pi Global Shutter](https://www.raspberrypi.com/products/raspberry-pi-global-shutter-camera/) for faster motion capture and custom-lens based on your needs&#x20;
   1. Requires a [RPi 5 Camera Cable](https://www.raspberrypi.com/products/camera-cable/) that is sold separately.
3. (_Alternative/additional_): See more at [Frigate's recommended camera hardware](https://docs.frigate.video/frigate/hardware#cameras).

The Raspberry Pi 5 has 2 (two) camera transceiver slots, so you can easily attach 2 native Raspberry Pi cameras.&#x20;

{% hint style="info" %}
See the [Frigate camera setup](https://docs.frigate.video/frigate/camera_setup) for more information on tuning stream configurations based on various goals for your deployment.
{% endhint %}

## AI Co-processor

(Required with camera) The AI co-processor is an efficient way to run the object detection model, much more efficient than CPU-alone.

{% hint style="info" %}
The AI co-processor is used by Frigate to run the object detection model, see Frigate's [supported hardware](https://docs.frigate.video/configuration/object_detectors) for more options and details. The Traffic Monitor assumes you are building on Raspberry Pi.
{% endhint %}

The below AI co-processors or detectors are capable of 100+ FPS with millisecond inference time, depending on the model and hardware. This means multiple camera feeds may be supported.

1. _Recommended:_  [Raspberry Pi AI HAT+](https://www.raspberrypi.com/products/ai-hat/) with Hailo-8 or Hailo-8L offers high-performance, power-efficient processing.
2. _(Older alternative, becoming expensive, hard-to-find, and obsolete)_ [Coral USB Accelerator](https://coral.ai/products/accelerator) is easy-to-use co-processor that you can connect to any computing device with a USB interface.
3. _(Older alternative, becoming expensive, hard-to-find, and obsolete)_ Coral HATs (Hardware-Attached-on-Top \[of a Raspberry Pi]) are more compact, upgradable than the USB accelerator:
   * [Rapsberry Pi M.2 HAT+](https://www.raspberrypi.com/products/m2-hat-plus/) pairs nicely with the [Coral M.2 Accelerator B+M Key](https://coral.ai/products/m2-accelerator-bm/) (not the A+E key!).

## Radar

(Recommended) Provides accurate speed and direction measurement.

1. [OmniPreSence OPS243-A Doppler Radar Sensor](https://omnipresense.com/product/ops243-doppler-radar-sensor/) - certified with same tests as law enforcement speed radars.  Detection up to 100-meters away. &#x20;

## Other Sensors

(Optional) For additional environmental data.

1. Air quality (AQ) sensor: [Enviro+](https://www.pishop.us/product/enviro-for-raspberry-pi/) paired with the (recommended) [Particulate Matter (PM) Sensor](https://www.pishop.us/product/pms5003-particulate-matter-sensor-with-cable/).  Also pick up a longer ribbon cable, we recommend the [male-to-female GPIO ribbon cable](https://www.pishop.us/product/male-to-female-gpio-ribbon-cable/).&#x20;

{% hint style="info" %}
Get AQ sensor details and capabilities on the [air-quality-aq-payload.md](sensor-payloads/air-quality-aq-payload.md "mention") page.
{% endhint %}

## Enclosure (weather-resistant box)

* _Print it yourself_:  We offer a 3D printable model so you can build the truly open source Traffic Monitor.  Visit our open source repository [greendormer/tm-enclosure-3d](https://github.com/greendormer/tm-enclosure-3d) for details and parts list.
* _Purchase_: _(coming soon)_ Purchase the box or a kit to assemble yourself.&#x20;
* _Alternative DIY_: There are many waterproof electrical junction boxes that may be modified to fit your needs with the traffic monitor. Rough dimensions to fit the Traffic Monitor components including the camera and radar should be around 9"x7"x4" such as the [TICONN IP67 ABS Enclosure](https://www.amazon.com/gp/product/B0B87X944Z).

[^1]: Your Mileage May Vary

[^2]: kiloWatt-hours
