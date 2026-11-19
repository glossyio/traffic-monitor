---
description: The path each object took across the camera's picture, as stored in the events table, and how to draw it or place it on the road.
---

# Object paths

For every object it tracks, Frigate keeps a short list of points that says where the object went in the camera's picture. The Traffic Monitor stores that list with the event, in the `path_data` column of the [events](events-payload.md) table. A path is numbers only, never a picture.

## Format

A path is a JSON array of points, each `[[x, y], t]`:

* `x` and `y` are a position as a fraction of the frame, from 0 to 1, with four decimals. The origin is the top-left corner of the picture: `x` runs to the right and `y` runs down.
* The position is the bottom centre of the object's box, which is roughly where the object touches the ground.
* `t` is the time of the frame, in Unix seconds.

For example, `[[[0.25, 0.5], 1793000000.2], [[0.75, 0.55], 1793000003.9]]` is an object that crossed from the left half of the picture to the right in under four seconds.

## How many points

Frigate adds a point when it first sees the object and again at the next frame. After that it adds one only when the object has moved at least 5% of the frame's diagonal since the last point, which for a 16:9 picture is about 0.057 in these units. A straight crossing of the frame gives about 20 points. Only objects that moved are recorded.

The device keeps at most 100 points per event. A longer path is thinned evenly to 100, keeping the first and the last point.

## Draw a path

To draw a path the way Frigate's **Tracking details** view does, multiply each point's `x` by the picture's width and `y` by its height, draw straight lines between consecutive points, and put a dot on each. Draw it over any picture from the same camera with the same aspect ratio as Frigate's detect stream. The path is the raw positions: there is no smoothing, and nothing in it knows where the road is.

## From the picture to the road

A point in the picture becomes a position on the road only with a mapping for that camera's view, and any change to the camera's position or aim needs a new one. The usual way, for a flat road, is four or more spots on the road surface that you can find both in the picture and on the ground, in metres or on an aerial photo. Four such pairs give a standard plane-to-plane mapping, a [homography](https://en.wikipedia.org/wiki/Homography_(computer_vision)). A Frigate zone set up for [speed estimation](../configuration/frigate-config.md#speed-without-a-radar), drawn as a true rectangle on the road with the real length of each side, works as those four spots.

How close the result gets:

* Bicycles and pedestrians place well, because the bottom of their box is close to where they touch the road.
* A car seen at an angle is placed closer to the camera than it is, by up to about half its width.
* Error grows with distance. From a camera 2 m high, a spot 20 m away is seen about 6° below level, so one degree of error in the camera's tilt moves that spot by 3 to 4 m.
* Error also grows at the edges of the frame, where a wide lens bends the picture in a way a flat mapping doesn't correct, and on a road that isn't flat.
* The first and last points are the weakest, because the edge of the frame cuts the object's box.

Which lane or side of the road an object used is realistic to work out near the camera and in the middle distance; exact wheel positions are not.

## What else is in the row

The same row holds the object's box in the last frame Frigate processed (`box`) and in its best frame (`best_box`), each as `[left, top, width, height]` fractions of the frame, the time of the best frame, and Frigate's own speed estimate with its unit and its angle across the picture. [Columns](events-payload.md#columns) describes each one.
