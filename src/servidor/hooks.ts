import { useServidor } from './Servidor'
import type { Estado, Persona } from './tipos'

/** Lo que se sabe de la fiesta sin haber preguntado a nadie: con esto la invitación se pinta al instante y también sin red. */
export const ESTADO_INICIAL: Estado = {
  now: new Date(0).toISOString(),
  version: 0,
  known: false,
  event: {
    phase: 'invitacion',
    starts_at: '2026-10-24T18:00:00-06:00',
    address_reveal_at: null,
    address_revealed: false,
    address: null,
    paused_at: null,
    opening_kill: false,
    door_code_required: false,
    rehearsal: false,
    durations: { round: 1200, vote: 180, tiebreak: 60, kill: 90, pause: 30 },
    rsvp_count: 0,
    present_count: 0,
  },
}

/** El estado de un jugador ya cargado, con lo más usado a mano. Solo se usa dentro de pantallas que se pintan tras el primer estado. */
export function useJuego() {
  const contexto = useServidor<Estado>()
  const e = contexto.estado as Estado
  const me = e.me!
  const game = e.game ?? null
  const ronda = game?.round ?? null
  const jugadores = e.players ?? []
  const pausadoEn = e.event.paused_at
  return { ...contexto, e, me, game, ronda, jugadores, pausadoEn }
}

/** El próximo vencimiento del juego (ISO), o null. Al llegar, el cliente le recuerda al servidor que avance. */
export function plazoDelJuego(e: Estado): string | null {
  if (e.event.paused_at || e.event.phase !== 'jugando') return null
  const g = e.game
  if (!g) return null
  if (g.ended) return g.next_deal_at
  const r = g.round
  if (!r) return null
  if (r.state === 'veredicto') return r.verdict?.kill_ends_at ?? null
  return r.ends_at
}

export const nombres = (personas: Persona[] | undefined | null) => (personas ?? []).map(p => p.name)

/** "Ana", "Ana y Luis", "Ana, Luis y Sofía". */
export function lista(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`
}
