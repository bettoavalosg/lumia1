import { lista, useJuego } from '../servidor/hooks'
import type { EntradaBitacora } from '../servidor/tipos'

function texto(h: EntradaBitacora): string {
  const v = h.verdict
  if (h.number === 0 && h.victim) return `La noche empezó con sangre: cayó ${h.victim.name}.`
  if (!v) return h.victim ? `Cayó ${h.victim.name}.` : 'Sin novedades.'
  if (v.correct) return `Acusaron a ${v.accused?.name}: era el asesino.`
  const beben = v.drinkers.length ? ` Bebieron ${lista(v.drinkers.map(d => d.name))}.` : ' Nadie bebió.'
  const cabeza = v.tie ? 'Empate sin resolver.' : v.accused ? `Acusaron a ${v.accused.name}: era inocente.` : 'Nadie votó.'
  const secreto = v.secret ? ` Salió a la luz un secreto sobre ${v.secret.about}.` : ''
  const cayo = h.victim ? ` Cayó ${h.victim.name}.` : ''
  return `${cabeza}${beben}${secreto}${cayo}`
}

/** Lo que va pasando en esta partida, ronda por ronda. */
export function Bitacora() {
  const { game, ronda } = useJuego()
  if (!game) {
    return (
      <section className="j-pantalla">
        <h1 className="sr-only">Bitácora</h1>
        <p className="j-etiqueta" aria-hidden="true">
          Bitácora
        </p>
        <p className="j-texto">Todavía no ha pasado nada. Es la calma antes de la noche.</p>
      </section>
    )
  }
  const historia = game.history.filter(h => h.number > 0 || h.victim)
  const enCurso = !game.ended && ronda && !ronda.verdict && ronda.number > 0
  return (
    <section className="j-pantalla j-bitacora">
      <h1 className="sr-only">Bitácora de la partida {game.number}</h1>
      <p className="j-etiqueta" aria-hidden="true">
        Bitácora · Partida {game.number}
      </p>
      {historia.length === 0 && !enCurso && <p className="j-texto">Todavía no ha pasado nada.</p>}
      <ol className="j-bitacora-lista">
        {historia.map(h => (
          <li key={h.number}>
            <span className="j-ronda-n">{h.number === 0 ? 'Apertura' : `Ronda ${h.number}`}</span>
            <p>{texto(h)}</p>
          </li>
        ))}
        {enCurso && (
          <li className="en-curso">
            <span className="j-ronda-n">Ronda {ronda.number}</span>
            <p>En curso…</p>
          </li>
        )}
      </ol>
      {game.ended && (
        <p className="j-texto destacado">
          {game.result === 'atrapado' ? 'Fin de la partida: atraparon al asesino.' : game.result === 'asesino_gana' ? 'Fin de la partida: ganó el asesino.' : 'La partida se canceló.'}
        </p>
      )}
    </section>
  )
}
