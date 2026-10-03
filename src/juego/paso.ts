import { prefiereMenosMovimiento } from '../lib/movimiento'
import { useLatido } from '../servidor/reloj'
import { useServidor } from '../servidor/Servidor'

/**
 * En qué momento de una revelación vamos, según cuánto tiempo pasó desde `desde` (hora del servidor).
 * `tiempos[i]` es cuándo empieza el paso i+1. Al recargar a media revelación se ve dónde va, no desde el principio.
 */
export function usePaso(desde: string | null | undefined, tiempos: number[]): number {
  const { ahora } = useServidor()
  useLatido(150)
  if (!desde || prefiereMenosMovimiento()) return tiempos.length
  const t = ahora() - Date.parse(desde)
  let paso = 0
  for (let i = 0; i < tiempos.length; i++) if (t >= tiempos[i]) paso = i + 1
  return paso
}
