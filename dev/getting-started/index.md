# Getting Started

## Step 1: Get your Traffic Monitor

The traffic monitor requires the [Recommended Hardware](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/recommended-hardware/index.md) and [software installation](https://docs.trafficmonitor.ai/dev/software-installation/index.md) before you can begin capturing roadway data.

There are two ways to get started:

- **[Build It!](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/index.md)**

  ______________________________________________________________________

  See our [Build your own device (DIY)](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/index.md) guide. The software is open source and components are available retail. Customize to your heart's content.

- **Buy It!** (*coming soon*)

  ______________________________________________________________________

  Purchase a pre-built traffic monitor or kit from the Roadway Biome Project.

## Step 2: Plan your Deployment

The traffic monitor must be placed with a good view of the roadway. See the [Deployment and Mounting Guide](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/index.md) for more information on the most common deployment types:

1. [Temporary deployments](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/#temporary-deployments) allow you to set up on the right-of-way or sidewalk next to a roadway to get counts for a short time.
1. [Permanent deployments](https://docs.trafficmonitor.ai/dev/deployment-and-mounting-guide/#permanent-deployments) are geared towards setting up a traffic monitor in a location to get 24/7 counts and monitoring.

## Step 3: Set up your Device

After you have your traffic monitor built, software installed, and physically set up (mounted), it is time to boot it up! To get the best data and most out of the device, follow these steps:

1. [Setup Guide](https://docs.trafficmonitor.ai/dev/setup-guide/index.md)
1. [Frigate Config](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/index.md) will guide you in setting up the object detection capabilities by turning on the camera and detection and defining zones.
1. [Node-RED Config](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/index.md) will turn on additional data collection capabilities, such as pairing your camera with the radar and other sensors, sharing your de-identified event data with another system or data provider, and more!

## Step 4: Collect and Share that Data

The traffic monitor will now run 24/7 collecting the data you set up. It will automatically restart if the power cycles, even if you are not there to reset it.

You can view the on-device dashboards, review event snapshots and clips in Frigate, download the local database, or view data shared with another data provider.

Consider pairing the Traffic Monitor with physical displays to show daily counts of cars, bikes, and pedestrians. The sky is the limit! Learn more and share via the [TM GitHub Show and tell](https://github.com/glossyio/traffic-monitor/discussions/new?category=show-and-tell) or our [TM Zulip chat](https://trafficmonitor.zulipchat.com/).

LED Display showing daily counts capture with the traffic monitor
