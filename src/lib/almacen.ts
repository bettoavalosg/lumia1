// localStorage sin sobresaltos: en modo privado o con el almacenamiento bloqueado, todo sigue funcionando (sin recordar).
const memoria = new Map<string, string>()

export function leerLocal(clave: string): string | null {
  try {
    return localStorage.getItem(clave) ?? memoria.get(clave) ?? null
  } catch {
    return memoria.get(clave) ?? null
  }
}

export function guardarLocal(clave: string, valor: string | null): void {
  try {
    if (valor === null) localStorage.removeItem(clave)
    else localStorage.setItem(clave, valor)
  } catch {
    // sin almacenamiento
  }
  if (valor === null) memoria.delete(clave)
  else memoria.set(clave, valor)
}

/** La llave para recuperar el lugar en otro dispositivo, tal como la entregó el servidor. */
export const llaveGuardada = () => leerLocal('mariela.llave')
export const guardarLlave = (llave: string | null) => guardarLocal('mariela.llave', llave)
