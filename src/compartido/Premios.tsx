import { lista } from '../servidor/hooks'
import type { Ranking } from '../servidor/tipos'

type Campo = 'shots' | 'kills' | 'correct_votes' | 'votes_received'

const PREMIOS: { campo: Campo; titulo: string; unidad: (n: number) => string; pie: string }[] = [
  { campo: 'shots', titulo: 'Quien más bebió', unidad: n => (n === 1 ? '1 trago' : `${n} tragos`), pie: 'La noche se lo cobró.' },
  { campo: 'kills', titulo: 'Sangre fría', unidad: n => (n === 1 ? '1 víctima' : `${n} víctimas`), pie: 'Ni pestañeó.' },
  { campo: 'correct_votes', titulo: 'Ojo de lince', unidad: n => (n === 1 ? '1 acierto' : `${n} aciertos`), pie: 'Lo vio venir.' },
  { campo: 'votes_received', titulo: 'Blanco favorito', unidad: n => (n === 1 ? '1 voto en contra' : `${n} votos en contra`), pie: 'Todos lo miraron.' },
]

/** Los números de la noche: el podio de tragos y cuatro premios con nombre y apellido. */
export function Premios({ ranking, clase = '' }: { ranking: Ranking; clase?: string }) {
  const jugadores = ranking.players
  const podio = jugadores.filter(p => p.shots > 0).slice(0, 3)
  const premios = PREMIOS.map(p => {
    const max = Math.max(0, ...jugadores.map(j => j[p.campo]))
    return { ...p, max, ganadores: max > 0 ? jugadores.filter(j => j[p.campo] === max) : [] }
  }).filter(p => p.ganadores.length > 0)

  return (
    <div className={`premios ${clase}`}>
      <p className="premios-cifras">
        {ranking.games} {ranking.games === 1 ? 'partida' : 'partidas'} · {ranking.caught} {ranking.caught === 1 ? 'atrapado' : 'atrapados'} · {ranking.killer_wins}{' '}
        {ranking.killer_wins === 1 ? 'victoria' : 'victorias'} del asesino
      </p>
      {podio.length > 0 && (
        <ol className="podio" aria-label="Quién bebió más">
          {podio.map((p, i) => (
            <li key={p.id} className={`lugar-${i + 1}`}>
              <span className="podio-n">{['I', 'II', 'III'][i]}</span>
              <span className="podio-nombre">{p.name}</span>
              <span className="podio-cifra">{p.shots === 1 ? '1 trago' : `${p.shots} tragos`}</span>
            </li>
          ))}
        </ol>
      )}
      <ul className="premios-lista">
        {premios.map(p => (
          <li key={p.campo}>
            <span className="premio-t">{p.titulo}</span>
            <span className="premio-n">{p.ganadores.length > 3 ? `${p.ganadores.length} empatados` : lista(p.ganadores.map(g => g.name))}</span>
            <span className="premio-d">
              {p.unidad(p.max)} · {p.pie}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
