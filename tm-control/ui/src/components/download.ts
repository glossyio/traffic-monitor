// Saving what the device sent as a file: the Device page's diagnostics and the Detection page's model packages.

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
