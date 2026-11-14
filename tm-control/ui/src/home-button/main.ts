// The home button: a small link back to the control app, drawn over each proxied app's page (nginx adds the script
// tag). It lives in a shadow root so the app's styles and ours leave each other alone. It can be dragged to either
// side, tucked against an edge, and once the device answers it shows the hostname and puts it in the tab's title.
import { mdiHome } from '@mdi/js'
import { colorOf, type ColorName } from '../colors'
import { appOf, defaultPlace, dropped, isDrag, NARROW, readPlaces, savePlace, titled, topOf, type Place } from './place'

const ID = 'tm-home-button'
const LABEL = 'Traffic Monitor home'
// The button's height, round or pill
const SIZE = 40

// The custom properties the style reads, and the device color each one takes
const COLORS: [string, ColorName][] = [['--bg', 'background'], ['--fg', 'header_text'], ['--tx', 'body_text']]

// --t is the button's top and --h the window's height, both set as it is placed, so `top` below can keep it clear of a
// phone's notch and home bar (zero everywhere else).
const STYLE = `
:host{all:initial;${COLORS.map(([prop, name]) => `${prop}:${colorOf(undefined, name)}`).join(';')}}
[hidden]{display:none!important}
a,button{position:relative;top:clamp(calc(env(safe-area-inset-top,0px) + 8px - var(--t)),0px,calc(var(--h) - env(safe-area-inset-bottom,0px) - 48px - var(--t)));opacity:.6;transition:opacity .12s;-webkit-tap-highlight-color:transparent}
a{display:flex;align-items:center;justify-content:center;gap:6px;box-sizing:border-box;height:${SIZE}px;min-width:${SIZE}px;border-radius:${SIZE / 2}px;border:1px solid var(--fg);background:var(--bg);color:var(--fg);box-shadow:0 1px 4px rgb(0 0 0/.35);text-decoration:none;cursor:pointer;touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
a::before{content:"";position:absolute;inset:-3px}
a.pill{padding:0 14px 0 10px}
a.on{cursor:grabbing}
a:hover,a.on,button:hover,:focus-visible{opacity:1}
:focus-visible{outline:2px solid var(--fg);outline-offset:2px}
svg{width:22px;height:22px;fill:currentColor;flex:none}
span{color:var(--tx);font:600 13px/1 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;white-space:nowrap;max-width:16em;overflow:hidden;text-overflow:ellipsis}
button{display:block;width:24px;height:44px;margin:0;padding:0;border:0;background:none;cursor:pointer}
button::before{content:"";position:absolute;top:0;width:6px;height:44px;box-sizing:border-box;border:1px solid var(--bg);background:var(--fg)}
:host([data-side=left]) a{margin-left:calc(8px + env(safe-area-inset-left,0px))}
:host([data-side=right]) a{margin-right:calc(8px + env(safe-area-inset-right,0px))}
:host([data-side=left]) button{margin-left:env(safe-area-inset-left,0px)}
:host([data-side=right]) button{margin-right:env(safe-area-inset-right,0px)}
:host([data-side=left]) button::before{left:0;border-radius:0 3px 3px 0}
:host([data-side=right]) button::before{right:0;border-radius:3px 0 0 3px}
@media print{:host{display:none!important}}
@media (prefers-reduced-motion:reduce){a,button{transition:none}}
`

interface Device {
  hostname?: unknown
  theme?: { colors?: Record<string, string> }
}

export function start(win: Window = window, app: string | null = appOf(win.location.pathname)): void {
  if (app === null || win.top !== win.self) return
  const doc = win.document
  if (doc.getElementById(ID)) return

  let storage: Storage | null = null
  try {
    storage = win.localStorage
  } catch {
    // Storage refused: the button works, and forgets where it was
  }
  let saved: Place | null = readPlaces(storage)[app] ?? null
  let hostname = ''

  const host = doc.createElement('div')
  host.id = ID
  host.style.position = 'fixed'
  host.style.zIndex = '2147483647'
  const root = host.attachShadow({ mode: 'open' })
  root.innerHTML = `<style>${STYLE}</style><a href="/" aria-label="${LABEL}" draggable="false">`
    + `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${mdiHome}"/></svg><span hidden></span></a>`
    + '<button type="button" aria-label="Show the home button" hidden></button>'
  const link = root.querySelector('a')!
  const name = root.querySelector('span')!
  const handle = root.querySelector('button')!

  const narrow = () => win.innerWidth < NARROW
  const current = () => saved ?? defaultPlace(app, narrow())

  function moveTo(top: number) {
    host.style.top = `${top}px`
    host.style.setProperty('--t', `${top}px`)
    host.style.setProperty('--h', `${win.innerHeight}px`)
  }

  function place() {
    const where = current()
    host.dataset.side = where.side
    host.style.left = where.side === 'left' ? '0px' : ''
    host.style.right = where.side === 'right' ? '0px' : ''
    moveTo(topOf(where, win.innerHeight, SIZE))
    link.hidden = where.tucked
    handle.hidden = !where.tucked
    name.hidden = !hostname || narrow()
    link.classList.toggle('pill', !name.hidden)
  }

  function keep(where: Place) {
    saved = where
    savePlace(storage, app!, where)
    place()
  }

  // A press goes home; a drag moves the button and the click that ends it is swallowed
  let from: { x: number; y: number } | null = null
  let dragging = false
  let swallow = false
  const settle = () => {
    from = null
    dragging = false
    link.classList.remove('on')
  }
  link.addEventListener('dragstart', (event) => event.preventDefault())
  link.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return
    from = { x: event.clientX, y: event.clientY }
    dragging = false
    swallow = false
    link.classList.add('on')
    if (event.pointerId !== undefined && link.setPointerCapture) {
      try {
        link.setPointerCapture(event.pointerId)
      } catch {
        // Not capturing: the drag still follows while the pointer is over the button
      }
    }
  })
  link.addEventListener('pointermove', (event) => {
    if (!from || (!dragging && !isDrag(event.clientX - from.x, event.clientY - from.y))) return
    dragging = true
    host.dataset.side = ''
    host.style.right = ''
    host.style.left = `${event.clientX - (link.offsetWidth || SIZE) / 2}px`
    moveTo(event.clientY - SIZE / 2)
  })
  link.addEventListener('pointerup', (event) => {
    if (!from) return
    if (dragging) {
      swallow = true
      keep(dropped(event.clientX, event.clientY, win.innerWidth, win.innerHeight))
    }
    settle()
  })
  link.addEventListener('pointercancel', () => {
    settle()
    place()
  })
  link.addEventListener('click', (event) => {
    if (swallow) event.preventDefault()
    swallow = false
  })
  link.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return
    keep({ ...current(), tucked: true })
    handle.focus()
  })
  handle.addEventListener('click', () => {
    keep({ ...current(), tucked: false })
    link.focus()
  })

  place()
  doc.documentElement.appendChild(host)

  win.addEventListener('resize', function onResize() {
    if (!host.isConnected) win.removeEventListener('resize', onResize)
    else if (!dragging) place()
  })

  // The device's name for the button and the tab. Anything but a usable answer leaves the icon alone, quietly.
  const retitle = () => {
    const title = titled(hostname, doc.title)
    if (title !== doc.title) doc.title = title
  }
  win.fetch('/api/v1/system/device', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then((response) => (response.status === 200 ? response.json() : null))
    .then((device: Device | null) => {
      if (typeof device?.hostname !== 'string' || !device.hostname) return
      hostname = device.hostname
      name.textContent = hostname
      link.setAttribute('aria-label', `${LABEL}, ${hostname}`)
      for (const [prop, color] of COLORS) host.style.setProperty(prop, colorOf(device.theme?.colors, color))
      place()
      retitle()
      // Apps change their title as you move around in them; setting the same title again changes nothing, so this
      // doesn't loop
      const observer = new MutationObserver(() => {
        if (host.isConnected) retitle()
        else observer.disconnect()
      })
      observer.observe(doc.head ?? doc.documentElement, { childList: true, subtree: true, characterData: true })
    })
    .catch(() => {})
}
