import { formatoReloj, segundosRestantes, useLatido } from '../servidor/reloj'
import { useServidor } from '../servidor/Servidor'

interface Props {
  /** Vencimiento (ISO) medido con el reloj del servidor. */
  hasta: string | null
  /** Duración completa, en segundos: el anillo se vacía de 1 a 0. */
  total: number
  pausadoEn?: string | null
  /** Diámetro en rem. */
  tamano?: number
  etiqueta?: string
  /** Se ve más grande y más fino, para la tele. */
  grande?: boolean
}

/** Anuncia el tiempo restante sin hablar cada segundo: al minuto, y a los 30, 10 y 5 segundos. */
function descripcion(seg: number): string {
  if (seg >= 60) return `Quedan ${Math.ceil(seg / 60)} minutos`
  if (seg > 30) return 'Queda menos de un minuto'
  if (seg > 10) return 'Quedan 30 segundos'
  if (seg > 5) return 'Quedan 10 segundos'
  return seg > 0 ? 'Quedan 5 segundos' : 'Se acabó el tiempo'
}

/** Un reloj de bolsillo: números de Bodoni dentro de un anillo que se vacía. */
export function Cuenta({ hasta, total, pausadoEn = null, tamano = 13.5, etiqueta, grande = false }: Props) {
  const { ahora } = useServidor()
  useLatido(200)
  const seg = segundosRestantes(hasta, ahora(), pausadoEn)
  const fraccion = seg === null || total <= 0 ? 0 : Math.min(1, seg / total)
  const urgente = seg !== null && seg <= 10 && seg > 0
  const R = 92
  const C = 2 * Math.PI * R
  const anunciado = seg === null ? '' : descripcion(seg)

  return (
    <div className={`cuenta${urgente ? ' urgente' : ''}${grande ? ' grande' : ''}${pausadoEn ? ' pausada' : ''}`} style={{ '--d': `${tamano}rem` }}>
      <svg viewBox="0 0 200 200" aria-hidden="true" focusable="false">
        <circle className="pista" cx="100" cy="100" r={R} />
        <circle className="pista fina" cx="100" cy="100" r={R - 9} />
        <circle className="progreso" cx="100" cy="100" r={R} strokeDasharray={C} strokeDashoffset={C * (1 - fraccion)} transform="rotate(-90 100 100)" />
      </svg>
      <div className="centro" aria-hidden="true">
        <span className="numeros">{seg === null ? '—' : formatoReloj(seg)}</span>
        {etiqueta && <span className="etiqueta">{etiqueta}</span>}
      </div>
      <span className="sr-only" role="timer" aria-live="off">
        {anunciado}
      </span>
      <span className="sr-only" aria-live="polite">
        {anunciado}
      </span>
    </div>
  )
}
