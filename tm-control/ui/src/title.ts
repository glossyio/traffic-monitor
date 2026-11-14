// What the browser tab says: the unit's name and the page, then the product. Without a name (before login, on setup
// and the license pages, or when the name couldn't be read) it is just the product.
export function pageTitle(hostname: string, page: string | undefined): string {
  if (!hostname) return 'Traffic Monitor'
  return `${page ? `${hostname} · ${page}` : hostname} | Traffic Monitor`
}
