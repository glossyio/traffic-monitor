---
description: Configure Frigate object detection on the Traffic Monitor
---

# Frigate Config

Object detection is powered by [Frigate NVR](https://frigate.video/), which provides powerful capabilities for tuning and reviewing events. The Traffic Monitor is not directly affiliated with the Frigate NVR project.

Refer to [Frigate Configuration](https://docs.frigate.video/configuration/) docs for full list of available configuration options and descriptions.

## Recommended Traffic Monitor Settings

The recommended Traffic Monitor settings attempts to optimize the Frigate config for **object detection on roadways**. Each deployment presents unique scenarios and challenges with accurate and precise object detection.&#x20;

View [frigate-config.yml](https://github.com/glossyio/traffic-monitor/blob/main/docker-frigate/frigate-config.yaml) for the sample.

{% hint style="info" %}
Many settings will need to be uniquely tailored to your specific deployment.  See [deployment-and-mounting-guide.md](../deployment-and-mounting-guide.md "mention") for optimizing your placement.
{% endhint %}
