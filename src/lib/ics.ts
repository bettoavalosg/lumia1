/**
 * El evento de calendario del prototipo, línea por línea. Fin estimado: medianoche.
 * La dirección no va aquí: se revela después (Fase 3).
 */
export function invitacionIcs(): string {
  return [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//XOXO//Mariela 29//ES',
    'BEGIN:VEVENT', 'UID:mariela-29-20261024@xoxo', 'DTSTAMP:20260928T000000Z',
    'DTSTART:20261025T000000Z', 'DTEND:20261025T060000Z',
    'SUMMARY:Mariela cumple 29',
    'DESCRIPTION:All black. La dirección se revela unos días antes. XOXO',
    'END:VEVENT', 'END:VCALENDAR',
  ].join('\r\n')
}

export function descargarIcs(): void {
  const url = URL.createObjectURL(new Blob([invitacionIcs()], { type: 'text/calendar;charset=utf-8' }))
  const enlace = Object.assign(document.createElement('a'), { href: url, download: 'mariela-29.ics' })
  document.body.append(enlace)
  enlace.click()
  enlace.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
