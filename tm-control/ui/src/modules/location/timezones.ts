// A place's time zone on the Location page: the one it starts with, and the list the device offers.
import { api } from '../../api/client'

// The device's list of time zone names, as the Date and time page's picker uses it. It throws what the client throws.
export async function loadTimeZones(): Promise<string[]> {
  const { data } = await api.GET('/api/v1/time/timezones')
  return data as string[]
}

// The time zone a place starts with: its own, else the unit's clock's, else none. The browser's is never used.
export function startingTimeZone(place: string | null | undefined, clock: string | null): string | null {
  return place || clock || null
}
