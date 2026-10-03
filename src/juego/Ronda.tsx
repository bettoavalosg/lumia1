import { Cuenta } from '../compartido/Cuenta'
import { useJuego } from '../servidor/hooks'
import { useLatido } from '../servidor/reloj'
import { SelectorVictima } from './SelectorVictima'

const FRASES = [
  'Platiquen. Sospechen. Acusen. En persona, no por mensaje.',
  'Alguien aquí sonríe demasiado.',
  'Mira quién evita mirarte.',
  'El asesino también levanta la mano para votar.',
  'No confíes en quien te dice en quién confiar.',
  'Todos tienen algo que ocultar. Solo uno tiene un cuchillo.',
  'Una coartada demasiado buena también es sospechosa.',
  'Cuidado con quien ya decidió a quién acusar.',
]

/** Cambia de frase cada 25 s, según la hora del servidor, para que todos lean la misma. */
function useFrase(desde: string, semilla: number) {
  const { ahora } = useJuego()
  useLatido(1000)
  const pasos = Math.max(0, Math.floor((ahora() - Date.parse(desde)) / 25_000))
  return FRASES[(semilla + pasos) % FRASES.length]
}

export function Ronda({ irACarta }: { irACarta: () => void }) {
  const { e, me, ronda, jugadores, pausadoEn } = useJuego()
  const frase = useFrase(ronda!.state_since, ronda!.number)
  const vivos = jugadores.filter(p => p.in_game && p.alive)
  const caidos = jugadores.filter(p => p.in_game && p.alive === false)

  return (
    <section className="j-pantalla j-ronda">
      <h1 className="sr-only">Ronda {ronda!.number}</h1>
      <p className="j-etiqueta" aria-hidden="true">
        Ronda {ronda!.number}
      </p>
      <Cuenta hasta={ronda!.ends_at} total={e.event.durations.round} pausadoEn={pausadoEn} etiqueta="para votar" />
      <p className="j-frase" aria-live="off">
        {frase}
      </p>
      {me.alive === false && <p className="j-nota apagada">Has muerto. Sigues en la fiesta, pero ya no votas.</p>}

      <div className="j-vivos">
        <p className="j-subetiqueta">
          Con vida · <b>{vivos.length}</b>
        </p>
        <ul className="j-nombres">
          {vivos.map(p => (
            <li key={p.id} className={p.id === me.id ? 'yo' : undefined}>
              {p.name}
            </li>
          ))}
        </ul>
        {caidos.length > 0 && (
          <>
            <p className="j-subetiqueta">Ya no están · {caidos.length}</p>
            <ul className="j-nombres caidos">
              {caidos.map(p => (
                <li key={p.id}>{p.name}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <button type="button" className="primario" onClick={irACarta}>
        Ver mi carta
      </button>
    </section>
  )
}

/** La muerte de apertura: la noche empieza con sangre, y solo el asesino sabe a quién. */
export function Apertura({ irACarta }: { irACarta: () => void }) {
  const { e, me, ronda, pausadoEn } = useJuego()
  if (me.can_kill) {
    return (
      <section className="j-pantalla">
        <SelectorVictima
          hasta={ronda!.ends_at}
          total={e.event.durations.kill}
          titulo="La noche empieza contigo"
          texto="Elige a la primera víctima. Nadie sabe quién eres todavía: así ninguna votación empieza a ciegas."
        />
      </section>
    )
  }
  return (
    <section className="j-pantalla j-ronda">
      <p className="j-etiqueta">Antes de la primera ronda</p>
      <h1 className="j-titulo">La noche empieza con sangre.</h1>
      <p className="j-texto">Alguien está eligiendo a la primera víctima. Tú también tienes que saber tu carta.</p>
      <Cuenta hasta={ronda!.ends_at} total={e.event.durations.kill} pausadoEn={pausadoEn} tamano={9} />
      <button type="button" className="primario" onClick={irACarta}>
        Ver mi carta
      </button>
    </section>
  )
}
