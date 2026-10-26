---
description: >-
  Open source roadway counting and speed monitoring on a Raspberry Pi. Start
  here to build, set up, or use a Traffic Monitor.
---

# Traffic Monitor docs

[Traffic Monitor](https://www.trafficmonitor.ai/) is open source software that turns a Raspberry Pi 5 with a camera and a Doppler radar into a roadway counter and speed monitor. It counts pedestrians, bicycles, and vehicles, measures vehicle speeds, and keeps the data on the device.

<figure markdown="span">
  ![Illustration of a Traffic Monitor counting cars, bikes, and pedestrians on a street](assets/images/tm-roadway-graphic-1920x1080-color-bg_white.png#only-light)
  ![Illustration of a Traffic Monitor counting cars, bikes, and pedestrians on a street](assets/images/tm-roadway-graphic-1920x1080-color-bg_black-1.png#only-dark)
  <figcaption>Be counted</figcaption>
</figure>

Privacy is part of the design. Object detection runs on the device, the database records labels, speeds, and times rather than people, and you choose what leaves the device. [Data and privacy](data-and-payloads/data-overview.md) lists what the device stores, including the short-lived snapshots and clips that Frigate keeps by default.

Our mission is to democratize the power of AI tools to improve community safety and quality of life, through the ethical and transparent use of these capabilities.

## Where to start

<div class="grid cards" markdown>

-   **[Build your own device](build-your-own-device-diy/README.md)**

    ---

    Buy the parts, assemble the enclosure, and install the software.

-   **[Set up a pre-built unit](deployment-and-mounting-guide.md)**

    ---

    Choose a site, mount the device, then follow [First-time setup](setup-guide.md).

-   **[Work with the data](data-and-payloads/data-overview.md)**

    ---

    What the database holds, what each column means, and how to export it.

-   **[Contribute](development/contributing.md)**

    ---

    Code, docs, ideas, and deployment stories are all welcome.

</div>

Something not working? See [Troubleshooting and FAQ](help-and-faq/frequently-asked-questions.md), or ask in the [chat](https://trafficmonitor.zulipchat.com/) and [discussions](https://github.com/glossyio/traffic-monitor/discussions) listed under [Get support](help-and-faq/where-can-i-get-support.md).

## Thank you 🩵

Made possible by these unaffiliated open source projects:

* [Frigate NVR](https://github.com/blakeblackshear/frigate), which does the object detection
* [Node-RED](https://nodered.org/), which runs the Traffic Monitor logic and dashboards
* [Zulip](https://zulip.com/), which hosts the [Traffic Monitor chat](https://trafficmonitor.zulipchat.com/)
