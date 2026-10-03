/**
 * Lo que necesita la tarjeta «Mandar la invitación» del admin. Hace lo mismo que scripts/enviar_sms.py y comparte con él los casos de
 * teléfonos (scripts/casos_telefonos.json) y la primera línea del mensaje: si cambias uno, cambia el otro.
 */

/** Un teléfono como lo escribe la gente → E.164 (+525512345678), o null si no se puede. Sin «+» se toma como mexicano. */
export function telefonoE164(crudo: string): string | null {
  const texto = crudo.trim()
  let internacional = texto.startsWith('+')
  let digitos = texto.replace(/\D/g, '')
  if (!internacional && digitos.startsWith('00')) {
    // 001 415…: el prefijo para marcar al extranjero
    digitos = digitos.slice(2)
    internacional = true
  }
  if (!digitos) return null
  if (!internacional) {
    if (digitos.startsWith('044') || digitos.startsWith('045')) digitos = digitos.slice(3) // el marcado viejo de celular
    if (digitos.length === 10) digitos = `52${digitos}`
    else if (!((digitos.length === 12 || digitos.length === 13) && digitos.startsWith('52'))) return null
  }
  if (digitos.startsWith('521') && digitos.length === 13) digitos = `52${digitos.slice(3)}` // el 1 de los celulares (+52 1 …) ya no se marca desde 2019
  if (digitos.startsWith('52') && digitos.length !== 12) return null
  return /^[1-9]\d{7,14}$/.test(digitos) ? `+${digitos}` : null
}

/**
 * El mensaje: el tono de la invitación en una línea, de quién es (un mensaje con un enlace desde un número que no conocen parece spam si
 * no se presenta) y el enlace. No lleva la dirección: el servidor no la suelta hasta la hora que se fije.
 */
export function mensajeInvitacion(nombre: string, enlace: string): string {
  const quien = nombre.trim()
  return `Mariela cumple 29: hay fiesta en la CDMX y alguien no va a salir viva. XOXO\n${quien ? `${quien}, tu invitación` : 'Tu invitación'}: ${enlace}`
}

/**
 * sms:+525512345678?&body=… — el «?&» lo entienden iOS y Android. Sin teléfono, Mensajes se abre con el texto y se elige a quién.
 * El texto va escapado entero: un «&» o un «#» en un nombre no pueden cortarlo.
 */
export function enlaceSms(telefono: string | null, cuerpo: string): string {
  return `sms:${telefono ?? ''}?&body=${encodeURIComponent(cuerpo)}`
}

/** ¿Un nombre de servidor que solo se ve desde este dispositivo o esta red (localhost, 192.168.x.x…)? Un enlace así no lo abre nadie más. */
export function esDireccionLocal(hostname: string): boolean {
  return /^(localhost|\[::1\]|0\.0\.0\.0|127(\.\d+){3}|10(\.\d+){3}|192\.168(\.\d+){2}|172\.(1[6-9]|2\d|3[01])(\.\d+){2})$|\.local$/i.test(hostname)
}
