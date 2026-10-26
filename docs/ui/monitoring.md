---
description: The Monitoring dashboard: today's counts, car speed statistics, hourly and daily charts, and the latest events with their radar readings.
---

# Monitoring

Open `http://<device>/dashboard/monitoring`, or open **Dashboard** from the home page and choose **Monitoring** in the sidebar. Monitoring shows the counts and speed statistics for one camera and one radar at a time.

<figure markdown="span">
  ![Monitoring dashboard with numbered areas: sensor selection, speed statistics, daily counts, hourly chart, daily chart, and latest observations](../assets/images/tm-dash-2026-03-monitoring.png)
  <figcaption>The Monitoring page, numbered as in the list below</figcaption>
</figure>

1. **Sensor selection.** A radar and a camera picker, listing every sensor in [config.yml](../configuration/node-red-config.md#sensorscameras), enabled or not. The counts and statistics on this page follow the camera and radar selected on the legacy dashboard at `http://<device>/ui/`, not the selection here. On a device with one camera and one radar, they're the same.
2. **Car speed statistics** for the current day, which starts at 04:00 local time. They cover `car` events that passed through both `zone_capture` and `zone_radar` and got a speed from the radar. Speeds are absolute values, so inbound and outbound are pooled, and every value is rounded to a whole number.

    The percentiles come from sorting the day's cars by speed and splitting them into 20 groups of equal size, so they're approximate. With few cars, some stay empty: the 25th percentile needs 5 cars, the median 10, the 75th percentile and `iqr_upper` 15, and the 85th percentile 17.

    | Statistic | Meaning |
    |---|---|
    | `count` | Cars with a speed |
    | `mean_speed` | Average speed |
    | `p25_speed`, `p50_speed`, `p75_speed`, `p85_speed` | 25th, 50th (median), 75th, and 85th [percentile](https://en.wikipedia.org/wiki/Percentile) speeds. The 85th percentile is the usual basis for speed limits. |
    | `max_speed` | Fastest car |
    | `count_over_25` | Cars faster than 25, in the radar's units |
    | `iqr_upper` | The outlier line: `p75_speed` plus 1.5 times the [interquartile range](https://en.wikipedia.org/wiki/Interquartile_range) |
    | `iqr_upper_freq` | Cars faster than `iqr_upper`, the outliers |

3. **Today's counts** by object type for events that passed through `zone_capture`. The day starts at 04:00 local time, so from midnight until 04:00 these counts and the speed statistics are empty. Objects that pass in those hours are left out of the day's counts, but they appear in the hourly and daily charts.
4. **Hourly counts** by object type for the last 36 hours, for events that passed through `zone_capture`.
5. **Daily counts** by object type for the last 10 calendar days, for events that passed through `zone_capture`.
6. **Latest observations.** The 21 most recent events from any camera that passed through `zone_radar`, newest first, including events without a speed. Each card shows Frigate's thumbnail of the object, the direction, the speed, and the radar's raw readings from the start of the event to its end: how many there were ("radar hits"), the range of their magnitudes and speeds, and two charts, **Radar Magnitude** and **Radar Speed**. The charts show whether the readings came from one object or from several at once. They're the raw readings, not the ones the speed was worked out from. The list is kept in memory, so it empties when Node-RED restarts.

Counts and statistics come from the `events` table; see [Events](../data-and-payloads/events-payload.md). The same counts are published over MQTT on `tm/events`; see [MQTT and ThingsBoard](../data-and-payloads/integrations.md#tmevents).
