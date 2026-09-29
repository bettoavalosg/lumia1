export const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
export const EASE_IN_OUT = 'cubic-bezier(0.77, 0, 0.175, 1)'
export const EASE_LENTO = 'cubic-bezier(0.65, 0, 0.35, 1)'

/** Se consulta en el momento de animar: si la persona cambia la preferencia, la siguiente animación ya la respeta. */
export const prefiereMenosMovimiento = (): boolean => matchMedia('(prefers-reduced-motion: reduce)').matches

export const tienePunteroFino = (): boolean => matchMedia('(hover: hover) and (pointer: fine)').matches

/** Vibración corta en Android; en iOS no existe y algunos visores la bloquean. */
export function vibrar(patron: number | number[]): void {
  try {
    navigator.vibrate?.(patron)
  } catch {
    // Sin vibración: no pasa nada.
  }
}
