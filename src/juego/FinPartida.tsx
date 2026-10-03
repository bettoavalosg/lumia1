import { Cuenta } from '../compartido/Cuenta'
import { lista, nombres, useJuego } from '../servidor/hooks'
import { Revelacion } from './Veredicto'
import { usePaso } from './paso'

/** Entre partidas: se revela quién era el asesino y en un momento se reparten cartas nuevas. */
export function FinPartida() {
  const { e, game, ronda, pausadoEn } = useJuego()
  const g = game!
  const v = ronda?.verdict ?? null
  const paso = usePaso(v?.at, [0, 900, 2600, 4100, 5500, 7100])
  const asesinos = nombres(g.killers)
  const titulo = g.result === 'atrapado' ? 'La atraparon.' : g.result === 'asesino_gana' ? 'Ganó el asesino.' : 'Partida cancelada.'

  return (
    <section className="j-pantalla j-fin-partida">
      <p className="j-etiqueta">Fin de la partida {g.number}</p>
      <h1 className="j-titulo">{titulo}</h1>
      <p className="j-texto destacado">
        {asesinos.length > 1 ? 'Los asesinos eran ' : 'El asesino era '}
        <em>{lista(asesinos)}</em>.
        {g.result === 'asesino_gana' && ' Solo quedaba un inocente en pie.'}
      </p>
      {v && g.result === 'atrapado' && <Revelacion v={v} paso={paso} />}
      {g.next_deal_at && (
        <div className="j-espera">
          <p className="j-subetiqueta">Cartas nuevas en</p>
          <Cuenta hasta={g.next_deal_at} total={e.event.durations.pause} pausadoEn={pausadoEn} tamano={7.5} />
          <p className="j-nota chica">Todos reviven. Nadie es quien era.</p>
        </div>
      )}
    </section>
  )
}
