______________________________________________________________________

## description: The Movements dashboard: counts of objects by the sequence of zones they passed through, for checking against manual counts.

# Movements

Open `http://<device>/dashboard/movements`. Movements counts objects by the path they took through your zones, which is how you check the device against a manual count or confirm that the zones capture what you want.

Movements come from the `entered_zones` of each [event](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md), so they depend on how the [zones](https://docs.trafficmonitor.ai/dev/setup-guide/#3-adjust-the-zones) are drawn.

The Movements page

1. **Zones.** Tick the zones to include. The four standard `zone_*` zones are unticked by default, so that zones you drew for your own analysis stand out.
1. **Intermediate zones.** Choose **Show intermediate zones** to count each full sequence of zones separately, or **Show just initial & final zones** to group by where an object entered and where it left.
1. **Time range.** Start and end times; the last 7 days by default. In time zones east of UTC, or with a half-hour offset, the page shows no counts for any range.
1. **Counts** by object type for each zone sequence that matches.

## Example: a complex intersection

An intersection with many zones has dozens of possible movements. Each turn or crossing becomes its own row, which you can compare with a manual count sheet.

Twelve zones drawn on a busy five-way intersection

Manual confirmation counts; the left sheet matches the zones above
