// What each sharing choice sends, as the person sees it before ticking the box. The values are made up (the
// coordinates are an example, not a place this device is); the shapes are the ones the upload uses.

// Share data: an event with its speed, its path across the picture, and its box, a deployment row whose location is
// rounded to the stored precision, and the watch log, which every five minutes says whether each camera and radar was
// working
export const SHARE_DATA_EXAMPLE = JSON.stringify(
  {
    event: {
      camera: 'camera_1_3fa9c2',
      label: 'car',
      start_time: 1_793_000_000.2,
      end_time: 1_793_000_003.9,
      direction_calc: 'inbound',
      direction_source: 'zones_radar',
      speed_calc: 31.5,
      speed_unit: 'mph',
      speed_source: 'radar',
      radar_readings: 7,
      path_data: [
        [[0.25, 0.5], 1_793_000_000.2],
        [[0.75, 0.55], 1_793_000_003.9],
      ],
      box: [0.75, 0.5, 0.25, 0.25],
    },
    deployment: {
      survey_id: '3f9a1c2e-si',
      lat: 45.52,
      lon: -122.69,
      location_precision: 2,
    },
    watch: {
      cameras: [
        {
          time: 1_793_000_100,
          camera: 'camera_1_3fa9c2',
          config_enabled: 1,
          frigate_answers: 5,
          camera_answers: 5,
          camera_fps: 5,
          detection_fps: 0.4,
          detection_enabled: 1,
          camera_on: 1,
        },
      ],
      radars: [{ time: 1_793_000_100, radar: 'TM_RADAR_SERIAL_PORT_00', config_enabled: 1, port_open: 1, radar_answers: 5, radar_on: 1 }],
    },
  },
  null,
  2,
)

// Share the exact location: the coordinates as the place stores them, nothing rounded
export const EXACT_LOCATION_EXAMPLE = JSON.stringify(
  { survey_id: '3f9a1c2e-si', lat: 45.52252, lon: -122.6912 },
  null,
  2,
)

// The public map: one point, rounded to about 100 m
export const PUBLIC_MAP_EXAMPLE = JSON.stringify(
  { survey_id: '3f9a1c2e-si', mode: 'rounded_point', lat: 45.523, lon: -122.691 },
  null,
  2,
)
