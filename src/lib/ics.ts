/**
 * El evento de calendario del prototipo, línea por línea. Fin estimado: medianoche.
 * La dirección solo se agrega cuando el servidor ya la reveló.
 */
const escapar = (texto: string) => texto.replace(/[\\;,]/g, m => `\\${m}`).replace(/\r?\n/g, '\\n')

export function invitacionIcs(direccion?: string | null): string {
  return [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//XOXO//Mariela 29//ES',
    'BEGIN:VEVENT', 'UID:mariela-29-20261024@xoxo', 'DTSTAMP:20260928T000000Z',
    'DTSTART:20261025T000000Z', 'DTEND:20261025T060000Z',
    'SUMMARY:Mariela cumple 29',
    ...(direccion ? [`LOCATION:${escapar(direccion)}`] : []),
    `DESCRIPTION:${direccion ? 'All black. XOXO' : 'All black. La dirección se revela unos días antes. XOXO'}`,
    'END:VEVENT', 'END:VCALENDAR',
  ].join('\r\n')
}

export function descargarIcs(direccion?: string | null): void {
  const url = URL.createObjectURL(new Blob([invitacionIcs(direccion)], { type: 'text/calendar;charset=utf-8' }))
  const enlace = Object.assign(document.createElement('a'), { href: url, download: 'mariela-29.ics' })
  document.body.append(enlace)
  enlace.click()
  enlace.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
