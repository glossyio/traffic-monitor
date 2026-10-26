# Monitoring

Success

The local, on-device Traffic Monitor dashboard is available by [connecting directly to your traffic monitor](https://docs.trafficmonitor.ai/dev/setup-guide/#1-connect-to-your-device) via a web browser.

The Monitoring tab display counts and descriptive statistics among all your sensors.

## Sample screenshot

Monitoring tab sample

## Descriptions

1. Select your Radar and Camera in case you have multiple sensors on the unit. Sensors need to be defined and enabled in the [Node-RED Config](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/index.md).
1. Displays `car` object speed counts and descriptive statistics for those that moved through `zone_radar` since 0400 local time. Stats include:
1. count: Total count through valid area
1. mean_speed: Average speed among all cars
1. p25_speed: 25th [Percentile](https://en.wikipedia.org/wiki/Percentile) speed, also known as first quartile (Q1)
1. p50_speed: 50th Percentile speed, also known as [median](https://en.wikipedia.org/wiki/Median) speed
1. p75_speed: 75th Percentile speed, also known as third quartile (Q3)
1. p85_speed: 85th Percentile speed
1. max_speed: Maximum speed
1. count_over_25: Static set number for maximum speed (25 in set system; e.g. 25 mph)
1. iqr_upper: [Interquartile range](https://en.wikipedia.org/wiki/Interquartile_range) (IQR) calculated as p75 + 1.5 * IQR
1. iqr_upper_freq: (frequency of cars above the iqr_upper) Count of vehicles driving above the iq_upper (considered [outliers](https://en.wikipedia.org/wiki/Outlier) that are significantly faster than other vehicles)
1. Daily cumulative counts for all [Frigate-enabled objects](https://docs.frigate.video/configuration/objects) since 0400 local time.
1. Hourly cumulative counts by object for the last 36 hours.
1. Daily cumulative counts by object for the last 10 days.
1. Latest observations (to display images, [Frigate snapshots](https://docs.frigate.video/configuration/snapshots/) must be enabled).
