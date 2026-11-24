// The parade's travelers and its tally, kept apart from the component so they can be tested without a page.
import { mdiBike, mdiBus, mdiCar, mdiCat, mdiDog, mdiDuck, mdiTractor, mdiWalk } from '@mdi/js'

export interface Traveler {
  id: string
  icon: string
  one: string
  many: string
}

// The tally lists travelers in the order of these two lists, common ones first
export const COMMON: Traveler[] = [
  { id: 'walker', icon: mdiWalk, one: 'walking', many: 'walking' },
  { id: 'bicycle', icon: mdiBike, one: 'bicycle', many: 'bicycles' },
  { id: 'car', icon: mdiCar, one: 'car', many: 'cars' },
  { id: 'bus', icon: mdiBus, one: 'bus', many: 'buses' },
]

export const RARE: Traveler[] = [
  { id: 'dog', icon: mdiDog, one: 'dog', many: 'dogs' },
  { id: 'cat', icon: mdiCat, one: 'cat', many: 'cats' },
  { id: 'tractor', icon: mdiTractor, one: 'tractor', many: 'tractors' },
  { id: 'duck', icon: mdiDuck, one: 'duck', many: 'ducks' },
]

// How long one traveler takes to cross, and so how often one is counted
export const PASS_MS = 2000

// About one in twelve is a rare one. A second random number picks within the list, so a test can steer both.
export function pickTraveler(random: () => number = Math.random): Traveler {
  const list = random() < 1 / 12 ? RARE : COMMON
  return list[Math.min(list.length - 1, Math.floor(random() * list.length))]
}

// "Counted so far: 3 walking, 2 bicycles, 1 duck"; travelers not counted yet are left out
export function tallyText(counts: Record<string, number>): string {
  const parts = [...COMMON, ...RARE]
    .filter((t) => (counts[t.id] ?? 0) > 0)
    .map((t) => `${counts[t.id]} ${counts[t.id] === 1 ? t.one : t.many}`)
  return `Counted so far: ${parts.length ? parts.join(', ') : 'nothing yet'}`
}
