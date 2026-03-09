---
description: Set up to contribute back to the Traffic Monitor project
---

# Dev Environment

The Traffic Monitor software is completely open source, so you are welcome to modify your devices to fit your needs. If you think others will benefit from your changes, you are welcome to [join the community](../help-and-faq/where-can-i-get-support.md) and [contribute back](contributing.md)!

The [Traffic Monitor OSS repo](https://github.com/glossyio/traffic-monitor) is set up as a [monorepo](https://en.wikipedia.org/wiki/Monorepo) containing everything to get the TM up and running.

## Node-RED logic

[Node-RED](https://nodered.org/) provides the primary logic engine to the Traffic Monitor including:

* Accepting input from other applications, such as Frigate for object detection, and sensors such as the radar for speed measurement.
* Enriching events by attaching speed
* Saving payloads and data internally
* Sending data to downstream applications

To get started developing:&#x20;

1. Access the Node-RED interface:  `http://<you_ip>:1880` and enter the default username and password.
2. Start a New Project and Clone \[your fork of] the traffic-monitor repo.  This will completely reset the current project, so ensure you have saved any changes.
3. Change `flows.json` and `package.json` to the `docker/node-red-tm/data` directory locations so changes will be incorporated
4. Commit changes to the \[forked] repo in a new branch.
5. PR changes following the [contributing.md](contributing.md "mention") guidelines.
