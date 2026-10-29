// What a person notices when a unit restarts, for the confirmation, and the result written under the button. Keyed
// by the units the API can restart (UNITS in tm-control/backend/tm_control/modules/services/units.py).

interface Restart {
  notice: string // the confirmation's text
  result: string // shown under the button once the device has the request
}

const RESTARTS: Record<string, Restart> = {
  'traffic-monitor.service': {
    notice:
      "Frigate, Node-RED, and the dashboards stop for about a minute while the pod restarts. Traffic isn't counted meanwhile.",
    result: 'The pod is restarting. Frigate and Node-RED are back in about a minute.',
  },
  'frigate.service': {
    notice: "The camera view stops for about a minute while Frigate restarts. Traffic isn't counted meanwhile.",
    result: 'Frigate is restarting. The camera view is back in about a minute.',
  },
  'node-red-tm.service': {
    notice: "The dashboards stop for about a minute while Node-RED restarts. Traffic isn't counted meanwhile.",
    result: 'Node-RED is restarting. The dashboards are back in about a minute.',
  },
  'plate-recognizer.service': {
    notice: 'Plate reads stop for about a minute while Plate Recognizer restarts.',
    result: 'Plate Recognizer is restarting.',
  },
  'go2rtc_server.service': {
    notice: "The camera's video stops for a few seconds while the camera streams restart.",
    result: 'The camera streams are restarting.',
  },
  'revproxy.service': {
    notice: 'This page stops answering for a few seconds while the web proxy restarts.',
    result: 'The web proxy is restarting. If this page stops answering, reload it in a few seconds.',
  },
}

export function restartFor(unit: string): Restart {
  return RESTARTS[unit] ?? { notice: 'It stops for a moment while it restarts.', result: 'Restarting.' }
}
