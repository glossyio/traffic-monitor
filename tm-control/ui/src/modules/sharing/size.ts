// The database's size in words, counted in powers of 1024 as the Device page counts storage: under 1 MB, "less than
// 1 MB"; megabytes as a whole number while that number is under 1000; else gigabytes with one decimal.
const MB = 1024 ** 2
const GB = 1024 ** 3

export function sizeWords(bytes: number): string {
  if (bytes < MB) return 'less than 1 MB'
  const megabytes = Math.round(bytes / MB)
  if (megabytes < 1000) return `${megabytes} MB`
  return `${(bytes / GB).toFixed(1)} GB`
}
