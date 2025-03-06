---
description: Set up to contribute back to the Traffic Monitor project
---

# Dev Environment

The Traffic Monitor software is completely open source, so you are welcome to modify your devices to fit your needs. If you think others will benefit from your changes, you are welcome to [join the community](../help-and-faq/where-can-i-get-support.md) and [contribute back](contributing.md)!

The [Traffic Monitor OSS repo](https://github.com/glossyio/traffic-monitor) is set up as a [monorepo](https://en.wikipedia.org/wiki/Monorepo) containing everything to get the TM up and running.

## Node-RED

[Node-RED](https://nodered.org/) provides the primary logic engine to the Traffic Monitor including:

* Accepting input from other applications, such as Frigate for object detection, and sensors such as the radar for speed measurement.
* Enriching events by attaching speed
* Saving payloads and data internally
* Sending data to downstream applications

_(More instructions coming soon)_
