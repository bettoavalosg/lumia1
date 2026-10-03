// sessionStorage sin sobresaltos: recordar algo mientras dure la pestaña.
const memoria = new Map<string, string>()

export function leerSesion(clave: string): string | null {
  try {
    return sessionStorage.getItem(clave) ?? memoria.get(clave) ?? null
  } catch {
    return memoria.get(clave) ?? null
  }
}

export function guardarSesion(clave: string, valor: string): void {
  try {
    sessionStorage.setItem(clave, valor)
  } catch {
    // sin almacenamiento
  }
  memoria.set(clave, valor)
}
