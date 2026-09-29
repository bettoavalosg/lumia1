export type Parte = { clave: 'd' | 'h' | 'm' | 's'; valor: number; unidad: string }

const plural = (n: number, uno: string, varios: string) => (n === 1 ? uno : varios)

/** Lo que falta para la fiesta. Los días desaparecen al llegar a cero; `null` cuando ya es la hora. */
export function partesRestantes(ms: number): Parte[] | null {
  if (ms <= 0) return null
  const t = Math.floor(ms / 1000)
  const d = Math.floor(t / 86400)
  const h = Math.floor((t % 86400) / 3600)
  const m = Math.floor((t % 3600) / 60)
  const s = t % 60
  return [
    ...(d ? [{ clave: 'd' as const, valor: d, unidad: plural(d, 'día', 'días') }] : []),
    { clave: 'h', valor: h, unidad: plural(h, 'hora', 'horas') },
    { clave: 'm', valor: m, unidad: plural(m, 'minuto', 'minutos') },
    { clave: 's', valor: s, unidad: plural(s, 'segundo', 'segundos') },
  ]
}

/** Separador después de la parte `i`: comas, una "y" antes de la última y punto final. */
export const separador = (i: number, total: number) => (i < total - 2 ? ', ' : i === total - 2 ? ' y ' : '.')
