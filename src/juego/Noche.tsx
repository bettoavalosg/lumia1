import { useJuego } from '../servidor/hooks'
import { Antesala } from './Antesala'
import { FinPartida } from './FinPartida'
import { Apertura, Ronda } from './Ronda'
import { Veredicto } from './Veredicto'
import { Votacion } from './Votacion'

/** Qué escena toca ahora, según lo que dice el servidor. Aquí no se decide nada del juego: solo se elige qué pintar. */
export function Noche({ alVerInvitacion, irACarta }: { alVerInvitacion: () => void; irACarta: () => void }) {
  const { me, game, ronda } = useJuego()

  if (!game) return <Antesala alVerInvitacion={alVerInvitacion} />
  if (game.ended) {
    return game.next_deal_at ? <FinPartida /> : <Antesala alVerInvitacion={alVerInvitacion} nota="La partida se canceló. Mariela va a repartir otra vez." />
  }
  if (!me.in_game || !ronda) return <Antesala alVerInvitacion={alVerInvitacion} />

  switch (ronda.state) {
    case 'apertura':
      return <Apertura irACarta={irACarta} />
    case 'votacion':
    case 'desempate':
      // Cada etapa es una votación nueva: lo elegido en la anterior no se hereda.
      return <Votacion key={`${ronda.id}-${ronda.state}`} />
    case 'veredicto':
      return ronda.verdict ? <Veredicto /> : <Ronda irACarta={irACarta} />
    default:
      return <Ronda irACarta={irACarta} />
  }
}
