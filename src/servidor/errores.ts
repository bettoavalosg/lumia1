/** Un error del juego: `codigo` es para la máquina y `message` está listo para mostrarle a la persona. */
export class ErrorJuego extends Error {
  readonly codigo: string
  constructor(codigo: string, mensaje: string) {
    super(mensaje)
    this.name = 'ErrorJuego'
    this.codigo = codigo
  }
}

// Entre ventanas (el simulador comparte su servidor con iframes) `instanceof` no sirve: se mira la forma.
export const esErrorJuego = (e: unknown): e is ErrorJuego =>
  typeof e === 'object' && e !== null && 'codigo' in e && typeof (e as ErrorJuego).codigo === 'string' && e instanceof Error

/** Códigos que significan "no hay red" o "el servidor no respondió": se reintenta solo, sin alarmar. */
export const esErrorDeRed = (e: unknown) => esErrorJuego(e) && (e.codigo === 'sin_red' || e.codigo.startsWith('http_5'))

export function mensajeDe(e: unknown): string {
  if (esErrorJuego(e)) return e.message
  if (e instanceof Error && e.message) return e.message
  return 'Algo salió mal. Inténtalo otra vez.'
}
