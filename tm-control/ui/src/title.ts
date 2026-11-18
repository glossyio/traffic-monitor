// What the browser tab says: the unit's name and the page, then the product. Only an unknown name (the page shown
// when the control app isn't answering, or an answer with no usable name) leaves just the product.
export function pageTitle(hostname: string, page: string | undefined): string {
  if (!hostname) return 'Traffic Monitor'
  return `${page ? `${hostname} · ${page}` : hostname} | Traffic Monitor`
}
