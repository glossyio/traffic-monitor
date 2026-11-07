// Copying text for the person: the Device page's diagnostics and the Detection page's label lists.

// Select all of a textarea's text. iOS Safari ignores select() on a read-only textarea, so set the range as well.
export function selectAll(area: HTMLTextAreaElement) {
  area.focus()
  area.select()
  area.setSelectionRange(0, area.value.length)
}

// navigator.clipboard only exists on HTTPS, and the device is usually reached over plain HTTP. The older way works
// on both: put the text in a textarea, select it, and ask the browser to copy the selection. The browser may still
// refuse, because the tap that asked for it was a while ago once the text has arrived (iOS Safari is strict).
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the older way
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed' // off the page, so the page doesn't scroll to it
  area.style.opacity = '0'
  document.body.append(area)
  selectAll(area)
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
