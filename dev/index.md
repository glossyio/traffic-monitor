# Traffic Monitor docs

[Traffic Monitor](https://www.trafficmonitor.ai/) is open source software that turns a Raspberry Pi 5 with a camera and a Doppler radar into a roadway counter and speed monitor. It counts pedestrians, bicycles, and vehicles, measures vehicle speeds, and keeps the data on the device.

Be counted

Privacy is part of the design. Object detection runs on the device, the database records labels, speeds, and times rather than people, and nothing is sent to an outside server unless you set it up. [Data and privacy](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/index.md) lists what the device stores, including the short-lived snapshots and clips that Frigate keeps by default, and who on your network can see them.

Our mission is to democratize the power of AI tools to improve community safety and quality of life, through the ethical and transparent use of these capabilities.

## Where to start

- **[Build your own device](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/index.md)**

  ______________________________________________________________________

  Buy the parts, assemble the enclosure, and install the software.

- **[Set up a pre-built unit](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/index.md)**

  ______________________________________________________________________

  Choose a site, mount the device, then follow [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).

- **[Work with the data](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/index.md)**

  ______________________________________________________________________

  What the database holds, what each column means, and how to export it.

- **[Contribute](https://docs.trafficmonitor.ai/dev/development/contributing/index.md)**

  ______________________________________________________________________

  Code, docs, ideas, and deployment stories are all welcome.

Something not working? See [Troubleshooting and FAQ](https://docs.trafficmonitor.ai/dev/help-and-faq/frequently-asked-questions/index.md), or ask in the [chat](https://trafficmonitor.zulipchat.com/) and [discussions](https://github.com/glossyio/traffic-monitor/discussions) listed under [Get support](https://docs.trafficmonitor.ai/dev/help-and-faq/where-can-i-get-support/index.md).

## Thank you 🩵

Made possible by these unaffiliated open source projects:

- [Frigate NVR](https://github.com/blakeblackshear/frigate), which does the object detection
- [Node-RED](https://nodered.org/), which runs the Traffic Monitor logic and dashboards
- [Zulip](https://zulip.com/), which hosts the [Traffic Monitor chat](https://trafficmonitor.zulipchat.com/)
