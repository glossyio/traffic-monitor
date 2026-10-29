// Spans of time in words: "20 seconds ago", "3 minutes". Rounded to one unit, because a person reading a phone at the
// roadside needs "about how long", not "2 minutes 47 seconds".

function count(n: number, unit: string) {
  return `${n} ${unit}${n === 1 ? '' : 's'}`
}

// How long something lasts (or the size of a difference, so the sign is dropped): "45 seconds", "3 minutes", "2 days"
export function duration(seconds: number): string {
  const s = Math.round(Math.abs(seconds))
  if (s < 60) return count(s, 'second')
  const minutes = Math.round(s / 60)
  if (minutes < 60) return count(minutes, 'minute')
  const hours = Math.round(s / 3600)
  if (hours < 48) return count(hours, 'hour')
  return count(Math.round(s / 86400), 'day')
}

// How long ago something happened. Under 20 seconds is "just now"; under a minute counts in tens of seconds, so a
// line that updates every second doesn't flicker through every number.
export function ago(seconds: number): string {
  if (seconds < 20) return 'just now'
  if (seconds < 60) return `${Math.floor(seconds / 10) * 10} seconds ago`
  if (seconds < 3600) return `${count(Math.floor(seconds / 60), 'minute')} ago`
  if (seconds < 86400) return `${count(Math.floor(seconds / 3600), 'hour')} ago`
  return `${count(Math.floor(seconds / 86400), 'day')} ago`
}
