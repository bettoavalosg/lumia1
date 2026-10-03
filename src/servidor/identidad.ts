// La identidad de un invitado es un token al azar que vive en su dispositivo. El servidor solo guarda su hash.

const CLAVE_TOKEN = 'mariela.token'
const CLAVE_ADMIN = 'mariela.admin'

// Dentro del simulador cada teléfono trae su token en la URL (?como=…) y no toca el almacenamiento compartido:
// vive solo en memoria. `?como=` vacío es un teléfono sin registrar.
const prestado = new URLSearchParams(location.search).has('como')
let anulado: string | null = new URLSearchParams(location.search).get('como') || null

let enMemoria: Record<string, string> = {}

function leer(clave: string): string | null {
  try {
    return localStorage.getItem(clave) ?? enMemoria[clave] ?? null
  } catch {
    return enMemoria[clave] ?? null
  }
}

function escribir(clave: string, valor: string | null) {
  try {
    if (valor === null) localStorage.removeItem(clave)
    else localStorage.setItem(clave, valor)
  } catch {
    // Modo privado o almacenamiento bloqueado: dura lo que dure la pestaña.
  }
  if (valor === null) delete enMemoria[clave]
  else enMemoria[clave] = valor
}

export const esTokenPrestado = prestado

export const tokenDispositivo = (): string | null => (prestado ? anulado : leer(CLAVE_TOKEN))

export function nuevoToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function guardarToken(token: string) {
  if (prestado) anulado = token
  else escribir(CLAVE_TOKEN, token)
}

export function olvidarToken() {
  if (prestado) anulado = null
  else escribir(CLAVE_TOKEN, null)
}

// -- admin ---------------------------------------------------------------------------------------------
export const sesionAdmin = {
  leer(): string | null {
    const crudo = leer(CLAVE_ADMIN)
    if (!crudo) return null
    try {
      const { session, expires_at } = JSON.parse(crudo) as { session: string; expires_at: string }
      return Date.parse(expires_at) > Date.now() ? session : null
    } catch {
      return null
    }
  },
  guardar(session: string, expiresAt: string) {
    escribir(CLAVE_ADMIN, JSON.stringify({ session, expires_at: expiresAt }))
  },
  borrar() {
    escribir(CLAVE_ADMIN, null)
  },
}

/** La llave de la /tv viaja en el fragmento (#k=…) para que no quede en los registros del servidor. */
export function llaveDeLaTv(): string | null {
  const desdeUrl = new URLSearchParams(location.hash.replace(/^#/, '')).get('k')
  if (desdeUrl) {
    escribir('mariela.tv', desdeUrl)
    return desdeUrl
  }
  return leer('mariela.tv')
}
