// What each sharing choice sends, as the person sees it before ticking the box. The values are made up (the
// coordinates are an example, not a place this device is); the shapes are the ones the upload uses.

// Share data: an event with its speed, its path across the picture, its box, and how long it stood still and spent in
// each zone (stationary_time, stops, zone_times), a deployment row whose location is rounded to the stored precision
// and which says how the sensor is mounted (heading_deg, pitch_deg, height_m, view_distance_m, mount), the place's
// time zone (timezone), and, for a radar, where it points across the road and the lanes entered (road_angle_deg,
// lane_distance_m, lane_width_m, lanes_toward, lanes_away, turn_lane, toward_side), and for a radar or camera whether
// the view takes in an intersection (intersection; a camera's row sends null for the seven radar ones), the watch log, which every five minutes says whether each camera and radar was working, and the setup history: a row for the
// device, a row for each camera, and a row for each radar, sent when one opens or closes, with the model's fingerprint, the
// versions, each camera's detection settings, the zones that are on, and masks (never a model's title or file name, or
// a profile's key), and each radar's model, firmware, and settings (never its serial number)
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
      stationary_time: 0,
      stops: 0,
      zone_times: { zone_near: { time: 1.2, stationary: 0 }, zone_far: { time: 1.4, stationary: 0 } },
    },
    deployment: {
      survey_id: '3f9a1c2e-si',
      lat: 45.52,
      lon: -122.69,
      location_precision: 2,
      heading_deg: 135,
      pitch_deg: 12,
      height_m: 3.6,
      view_distance_m: 16.94,
      mount: 'pole',
      timezone: 'America/New_York',
      road_angle_deg: 20,
      lane_distance_m: 2.5,
      lane_width_m: 3.5,
      lanes_toward: 1,
      lanes_away: 1,
      turn_lane: null,
      toward_side: 'near',
      intersection: null,
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
    setup: {
      device: [
        {
          id: '1792000000000-3fa9c2e1-sd',
          started: 1_792_000_000_000,
          ended: null,
          tm_version: '0.8.0',
          tm_commit: '7e4a91b03c5d28f6a1b9d47e0c32f58a6b1d9e74',
          schema_version: 11,
          frigate_version: '0.18.2',
          unit_system: 'imperial',
          detector: 'hailo8l',
          model_id: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
          model_sha256: '9f2c4a7e5b1d83a60c47e2f19d5b8a3c71e04f6a2b9d8c5e3f1a7b4d6c80e925',
          model_kind: 'frigate_plus',
          model_trained_at: '2026-09-14T10:22:31Z',
          model_base: 'yolov9-s',
          model_type: 'yolo-generic',
          model_width: 320,
          model_height: 320,
          labels_available: ['bicycle', 'bus', 'car', 'motorcycle', 'person', 'truck'],
        },
      ],
      cameras: [
        {
          id: '1792000000000-5d7e0b42-sc',
          started: 1_792_000_000_000,
          ended: null,
          camera: 'camera_1_3fa9c2',
          detect_width: 1280,
          detect_height: 720,
          detect_fps: 5,
          stationary_threshold: 50,
          stationary_interval: 50,
          lens_hfov: null,
          labels_tracked: ['bicycle', 'bus', 'car', 'motorcycle', 'truck'],
          thresholds: { car: { min_area: 3000, min_score: 0.5, threshold: 0.7 } },
          zones: [
            {
              key: 'zone_near',
              enabled: true,
              corners: [
                [0.1, 0.9],
                [0.9, 0.9],
                [0.8, 0.7],
                [0.2, 0.7],
              ],
              distances: [12, 40, 12, 40],
              inertia: 3,
              loitering_time: 0,
              speed_threshold: null,
              objects: ['car', 'truck'],
              filters: {},
            },
          ],
          masks: {
            motion: [
              {
                enabled: true,
                corners: [
                  [0, 0],
                  [0.3, 0],
                  [0.3, 0.1],
                  [0, 0.1],
                ],
              },
            ],
            objects: [],
            object_filters: {},
          },
        },
      ],
      radars: [
        {
          id: '1792000000000-8c1d4e07-sr',
          started: 1_792_000_000_000,
          ended: null,
          radar: 'TM_RADAR_SERIAL_PORT_00',
          part_number: 'OPS243-A',
          firmware_version: '1.2.1',
          cosine_inbound_deg: 0,
          cosine_outbound_deg: 0,
          speed_unit: 'mph',
          sampling_rate: 20000,
          speed_min: 5,
          magnitude_min: 20,
        },
      ],
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
