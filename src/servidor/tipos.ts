// La forma del JSON que arma el servidor (supabase/migrations/*_estado.sql). Si cambia allá, cambia aquí.

export type Fase = 'invitacion' | 'lobby' | 'jugando' | 'fin'
export type EstadoRonda = 'apertura' | 'discusion' | 'votacion' | 'desempate' | 'veredicto' | 'cerrada'
export type Rol = 'asesino' | 'inocente'
export type Resultado = 'atrapado' | 'asesino_gana' | 'cancelada'
export type MotivoTrago = 'atrapado' | 'voto_fallido' | 'empate'
export type EstadoSecreto = 'pendiente' | 'aprobado' | 'rechazado' | 'revelado'

export interface Persona {
  id: string
  name: string
}

export interface Evento {
  phase: Fase
  starts_at: string
  address_reveal_at: string | null
  address_revealed: boolean
  address: string | null
  paused_at: string | null
  opening_kill: boolean
  door_code_required: boolean
  rehearsal: boolean
  durations: { round: number; vote: number; tiebreak: number; kill: number; pause: number }
  rsvp_count: number
  present_count: number
}

export interface JugadorPublico {
  id: string
  name: string
  checked_in: boolean
  bot: boolean
  in_game: boolean
  alive: boolean | null
}

export interface Conteo {
  id: string
  name: string
  votes: number
}

export interface Trago {
  id: string
  name: string
  reason: MotivoTrago
}

export interface Muerte {
  id: string
  name: string
  at: string
  auto?: boolean
}

export interface Veredicto {
  at: string
  accused: Persona | null
  correct: boolean | null
  tie: boolean
  stage: 1 | 2
  tally: Conteo[]
  first_tally: Conteo[] | null
  votes: { voter: string; target: string }[]
  drinkers: Trago[]
  secret: { about: string; text: string } | null
  victim: Muerte | null
  kill_ends_at: string | null
}

export interface Ronda {
  id: string
  number: number
  state: EstadoRonda
  stage: 1 | 2
  ends_at: string | null
  state_since: string
  votes_cast: number
  votes_expected: number
  candidates: Persona[]
  verdict: Veredicto | null
}

export interface EntradaBitacora {
  number: number
  state: EstadoRonda
  verdict: Veredicto | null
  victim: Muerte | null
}

export interface Partida {
  id: string
  number: number
  started_at: string
  ended: boolean
  ended_at: string | null
  result: Resultado | null
  next_deal_at: string | null
  killers: Persona[] | null
  alive_count: number
  round: Ronda | null
  history: EntradaBitacora[]
  last_kill: { victim: Persona; at: string } | null
}

export interface Yo {
  id: string
  name: string
  checked_in: boolean
  in_game: boolean
  alive: boolean | null
  role: Rol | null
  accomplices: Persona[]
  my_vote: Persona | null
  can_vote: boolean
  vote_targets: Persona[]
  can_kill: boolean
  kill_targets: Persona[]
  secret: { id: string; status: EstadoSecreto; about: string; text: string } | null
  push: boolean
}

export interface EstadisticaJugador {
  id: string
  name: string
  shots: number
  kills: number
  correct_votes: number
  votes_received: number
  times_killer: number
}

export interface Ranking {
  games: number
  caught: number
  killer_wins: number
  players: EstadisticaJugador[]
}

export interface Estado {
  now: string
  version: number
  event: Evento
  known?: boolean
  players?: JugadorPublico[]
  game?: Partida | null
  me?: Yo
  ranking?: Ranking | null
  door_code?: string | null
}

// -- admin ---------------------------------------------------------------------------------------------
export interface EventoAdmin extends Evento {
  door_code: string | null
  tv_key: string
  killers_threshold: number
  bots_delay_seconds: number
  clock_offset_seconds: number
}

export interface InvitadoAdmin {
  id: string
  name: string
  checked_in: boolean
  bot: boolean
  has_secret: boolean
  push: boolean
  device: boolean
  in_game: boolean
  alive: boolean | null
}

export interface SecretoAdmin {
  id: string
  about: string
  text: string
  status: EstadoSecreto
}

export interface EstadoAdmin {
  now: string
  version: number
  event: EventoAdmin
  players: InvitadoAdmin[]
  secrets: SecretoAdmin[]
  game: Partida | null
  ranking: Ranking
}
