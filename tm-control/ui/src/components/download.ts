// Saving what the device sent as a file: the Device page's diagnostics and the Detection page's model packages and model files.
// And starting a download the device serves itself: the Location page's database copy.

// A link to the data in memory, with the file's name, clicked once. Some browsers only follow a link that's in the
// page, and still read the file after click() returns, so it's freed later.
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

// Starts a download from an address on this device (the database copy's /storefiles link). It navigates to the address
// instead of fetching it: the browser then shows its own download progress, the file can be large, and Android's
// sign-in window (which hands a download to a helper) only follows a navigation, as the Dashboard's download does.
// Tests replace this, so no page is left.
export function openDownload(url: string) {
  window.location.assign(url)
}
