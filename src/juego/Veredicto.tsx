import { Cuenta } from '../compartido/Cuenta'
import { lista, useJuego } from '../servidor/hooks'
import type { Veredicto as TipoVeredicto } from '../servidor/tipos'
import { IconoCopa } from './iconos'
import { usePaso } from './paso'
import { SelectorVictima } from './SelectorVictima'

// Cuándo entra cada parte de la revelación, en ms desde el veredicto.
const TIEMPOS = [0, 900, 2600, 4100, 5500, 7100]

/** El veredicto de un fallo: quién fue acusado, quién bebe y qué secreto sale a la luz. El asesino elige a su víctima aquí mismo. */
export function Veredicto() {
  const { e, me, ronda, pausadoEn } = useJuego()
  const v = ronda!.verdict!
  const paso = usePaso(v.at, TIEMPOS)

  return (
    <section className="j-pantalla j-veredicto">
      {me.can_kill && (
        <SelectorVictima hasta={v.kill_ends_at} total={e.event.durations.kill} titulo="Fallaron. Ahora te toca a ti." texto="Elige a quién le toca caer. Si no eliges a tiempo, el azar lo hace por ti." />
      )}
      <p className="j-etiqueta">Veredicto</p>
      <Revelacion v={v} paso={paso} />
      {!me.can_kill && (
        <div className="j-espera">
          <p className="j-subetiqueta">El asesino está eligiendo…</p>
          <Cuenta hasta={v.kill_ends_at} total={e.event.durations.kill} pausadoEn={pausadoEn} tamano={6.5} />
        </div>
      )}
    </section>
  )
}

/** La revelación por partes. Cada parte aparece cuando le toca y se queda. */
export function Revelacion({ v, paso }: { v: TipoVeredicto; paso: number }) {
  const cabeza = v.tie ? 'Empate que no se rompió' : v.accused ? (v.stage === 2 ? 'Tras el desempate, acusaron a' : 'Acusaron a') : 'Nadie votó'
  const sentencia = v.correct
    ? 'Era el asesino.'
    : v.tie
      ? 'La sala no se puso de acuerdo. Fallaron.'
      : v.accused
        ? 'Era inocente. Fallaron.'
        : 'El silencio también es un voto. Fallaron.'

  return (
    <div className={`j-revela${v.drinkers.length > 6 ? ' muchos-beben' : ''}`}>
      <div className={`rev rev-cab${paso >= 1 ? ' on' : ''}`}>
        <p className="j-subetiqueta">{cabeza}</p>
      </div>
      {v.accused && (
        <div className={`rev rev-acu${paso >= 2 ? ' on' : ''}`}>
          <h1 className="j-titulo grande">
            <em>{v.accused.name}</em>
          </h1>
        </div>
      )}
      <div className={`rev rev-sen${paso >= 3 ? ' on' : ''}`}>
        <p className={`j-sentencia${v.correct ? ' acierto' : ''}`}>{sentencia}</p>
      </div>

      <div className={`rev rev-vot${paso >= 4 ? ' on' : ''}`}>
        {v.tally.length > 0 && (
          <div className="j-votos">
            <p className="j-subetiqueta">Los votos</p>
            <ul>
              {v.tally.map(t => (
                <li key={t.id}>
                  <span className="j-voto-nombre">{t.name}</span>
                  <span className="j-voto-barra" style={{ '--v': t.votes / v.tally[0].votes }} />
                  <b>{t.votes}</b>
                </li>
              ))}
            </ul>
            <details className="j-quien">
              <summary>Ver quién votó a quién</summary>
              <ul>
                {v.votes.map((x, i) => (
                  <li key={i}>
                    {x.voter} <span aria-label="votó por">→</span> {x.target}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </div>

      <div className={`rev rev-beb${paso >= 5 ? ' on' : ''}`}>
        <div className="j-beben">
          <p className="j-subetiqueta">Beben</p>
          {v.drinkers.length > 0 ? (
            <>
              <ul className="j-nombres bebedores">
                {v.drinkers.map(d => (
                  <li key={d.id}>
                    <IconoCopa />
                    {d.name}
                  </li>
                ))}
              </ul>
              <p className="j-nota chica">
                {v.drinkers[0].reason === 'atrapado'
                  ? 'Se atrapa, se brinda: el asesino paga.'
                  : v.drinkers[0].reason === 'empate'
                    ? `Los empatados: ${lista(v.drinkers.map(d => d.name))}.`
                    : `Votaron por ${v.accused?.name}. Un trago cada quien.`}
              </p>
            </>
          ) : (
            <p className="j-texto">Nadie bebe esta vez.</p>
          )}
        </div>
      </div>

      {!v.correct && (
      <div className={`rev rev-sec${paso >= 6 ? ' on' : ''}`}>
        {v.secret ? (
          <figure className="j-secreto">
            <p className="j-subetiqueta">Sale a la luz</p>
            <blockquote>
              <span className="j-secreto-sobre">
                Sobre <em>{v.secret.about}</em>
              </span>
              <p>{v.secret.text}</p>
            </blockquote>
            <figcaption>— Alguien que te quiere. XOXO</figcaption>
          </figure>
        ) : (
          <p className="j-nota">No quedaban secretos por revelar. Esta vez se salvaron.</p>
        )}
      </div>
      )}
    </div>
  )
}
