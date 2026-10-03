import { useEffect, useState } from 'react'

/** Segundos que faltan para `hasta`, medidos con el reloj del servidor. Si hay pausa, el reloj está congelado en ese instante. */
export function segundosRestantes(hasta: string | null, ahora: number, pausadoEn: string | null = null): number | null {
  if (!hasta) return null
  const referencia = pausadoEn ? Date.parse(pausadoEn) : ahora
  return Math.max(0, (Date.parse(hasta) - referencia) / 1000)
}

/** "18:04", "0:09", "1:02:10". */
export function formatoReloj(segundos: number): string {
  const total = Math.ceil(segundos)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const dos = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${dos(m)}:${dos(s)}` : `${m}:${dos(s)}`
}

/** Un reloj que late `cada` milisegundos. Se usa para pintar cuentas regresivas. */
export function useLatido(cada = 250): number {
  const [latido, setLatido] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setLatido(n => n + 1), cada)
    return () => clearInterval(id)
  }, [cada])
  return latido
}
