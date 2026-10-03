import { useState, type FormEvent } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { vibrar } from '../lib/movimiento'
import { mensajeDe } from '../servidor/errores'
import { useJuego } from '../servidor/hooks'
import { tokenDispositivo } from '../servidor/identidad'
import { Instalar } from './Instalar'

interface Props {
  alVerInvitacion: () => void
  /** Una nota sobre por qué se está aquí: la partida se canceló, o empezó sin ti. */
  nota?: string
}

/** Antes del reparto: llegar, ver quién ya está y esperar. */
export function Antesala({ alVerInvitacion, nota }: Props) {
  const { e, me, jugadores, game, backend } = useJuego()
  const presentes = jugadores.filter(p => p.checked_in)
  const total = e.event.rsvp_count
  const enCurso = Boolean(game && !game.ended)

  return (
    <section className="j-pantalla j-antesala">
      <p className="j-etiqueta">{enCurso ? 'En la lista' : 'Antesala'}</p>
      <h1 className="j-titulo">
        Ya estás dentro, <em>{me.name}</em>.
      </h1>
      {nota && <p className="j-texto destacado">{nota}</p>}

      {me.checked_in ? (
        <p className="j-texto">
          {enCurso
            ? 'La partida ya empezó sin ti. Entras en la siguiente: mientras tanto, mira cómo va la noche.'
            : 'La noche ya te vio llegar. En cuanto Mariela reparta las cartas, la tuya aparece aquí.'}
        </p>
      ) : (
        <Llegada />
      )}

      <div className="j-llegados" aria-live="polite">
        <p className="j-contador">
          <b>{presentes.length}</b> de {total} ya llegaron
        </p>
        <ul className="j-nombres">
          {presentes.map((p, i) => (
            <li key={p.id} style={{ '--i': Math.min(i, 24) }} className={p.id === me.id ? 'yo' : undefined}>
              {p.name}
            </li>
          ))}
        </ul>
      </div>

      {!enCurso && <p className="j-susurro">Mírense bien. Después del reparto, nadie será quien dice ser.</p>}

      <SecretoRechazado />
      <Instalar />
      <button type="button" className="j-enlace" onClick={alVerInvitacion}>
        Ver la invitación
      </button>
      {backend.modo === 'demo' && window.parent === window && (
        <a className="j-enlace" href="/demo">
          Abrir el simulador
        </a>
      )}
    </section>
  )
}

function Llegada() {
  const { e, llamar } = useJuego()
  const avisar = useAvisos()
  const [codigo, setCodigo] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  const pide = e.event.door_code_required

  const enviar = async (ev: FormEvent) => {
    ev.preventDefault()
    setError('')
    setEnviando(true)
    try {
      await llamar('check_in', { p_token: tokenDispositivo(), p_code: pide ? codigo : null })
      vibrar(20)
      avisar('Anotada tu llegada.', 'ok')
    } catch (err) {
      setError(mensajeDe(err))
      vibrar([8, 30, 8])
    }
    setEnviando(false)
  }

  return (
    <form className="j-llegada" onSubmit={enviar}>
      <p className="j-texto">Cuando cruces la puerta, avísale a la noche.</p>
      {pide && (
        <div className="campo">
          <label htmlFor="codigo-puerta">Código de la puerta</label>
          <input
            id="codigo-puerta"
            value={codigo}
            onChange={ev => setCodigo(ev.target.value)}
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            maxLength={12}
            aria-describedby="codigo-ayuda codigo-error"
            aria-invalid={error ? true : undefined}
          />
          <p className="hint" id="codigo-ayuda">
            Está en la pantalla de la entrada.
          </p>
        </div>
      )}
      <p className="error" id="codigo-error" role="alert">
        {error}
      </p>
      <button type="submit" id="j-estoy-aqui" className="primario" disabled={enviando || (pide && !codigo.trim())}>
        {enviando ? 'Un momento…' : 'Estoy aquí'}
      </button>
    </form>
  )
}

/** Si el admin rechazó tu secreto, tienes que escribir otro para no quedar fuera del juego. */
function SecretoRechazado() {
  const { me, backend, refrescar } = useJuego()
  const [v, setV] = useState({ quien: '', secreto: '' })
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)
  if (me.secret?.status !== 'rechazado') return null

  const enviar = async (ev: FormEvent) => {
    ev.preventDefault()
    setEnviando(true)
    setError('')
    try {
      await backend.rpc('replace_secret', { p_token: tokenDispositivo(), p_about: v.quien, p_text: v.secreto })
      await refrescar()
    } catch (err) {
      setError(mensajeDe(err))
    }
    setEnviando(false)
  }

  return (
    <form className="j-tarjeta j-reemplazo" onSubmit={enviar}>
      <p className="j-titulo chico">Tu secreto no pasó la revisión.</p>
      <p className="j-texto">Escribe otro, más suave. Que dé risa, no que termine amistades.</p>
      <div className="campo">
        <label htmlFor="r-quien">¿De quién es?</label>
        <input id="r-quien" maxLength={40} value={v.quien} onChange={ev => setV(x => ({ ...x, quien: ev.target.value }))} />
      </div>
      <div className="campo">
        <label htmlFor="r-secreto">El secreto</label>
        <textarea id="r-secreto" maxLength={280} value={v.secreto} onChange={ev => setV(x => ({ ...x, secreto: ev.target.value }))} />
      </div>
      <p className="error" role="alert">
        {error}
      </p>
      <button type="submit" className="secundario" disabled={enviando || !v.quien.trim() || !v.secreto.trim()}>
        {enviando ? 'Enviando…' : 'Enviar otro'}
      </button>
    </form>
  )
}
