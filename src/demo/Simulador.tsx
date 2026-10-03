import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { Cargando } from '../compartido/Cargando'
import { Cera } from '../compartido/Sprite'
import { SesionContexto, useAdmin } from '../admin/comun'
import type { Backend } from '../servidor/backend'
import { useBackend } from '../servidor/BackendContexto'
import { mensajeDe } from '../servidor/errores'
import { plazoDelJuego } from '../servidor/hooks'
import { guardarToken, nuevoToken, sesionAdmin } from '../servidor/identidad'
import { ServidorProvider, useServidor } from '../servidor/Servidor'
import type { EstadoAdmin } from '../servidor/tipos'
import '../styles/juego.css'
import '../styles/admin.css'
import '../styles/simulador.css'
import { PIN_DEMO } from '../servidor/demo'

/** Prueba la noche entera sin nadie más: teléfonos, tele y controles, todos sobre el mismo Postgres del navegador. */
export default function Simulador() {
  const backend = useBackend()
  const [sesion, setSesion] = useState<string | null>(null)
  const [fallo, setFallo] = useState('')

  useEffect(() => {
    backend
      .rpc<{ ok: boolean; session?: string; expires_at?: string; message?: string }>('admin_login', { p_pin: PIN_DEMO })
      .then(r => {
        if (r.ok && r.session && r.expires_at) {
          // El panel de admin del simulador (otro iframe) entra con esta misma sesión.
          sesionAdmin.guardar(r.session, r.expires_at)
          setSesion(r.session)
        } else setFallo(r.message ?? 'No pude entrar como admin.')
      })
      .catch(e => setFallo(mensajeDe(e)))
  }, [backend])

  if (backend.modo !== 'demo') {
    return (
      <div className="cargando">
        <p>El simulador solo funciona con el servidor de demostración.</p>
      </div>
    )
  }
  if (fallo) return <div className="cargando"><p>{fallo}</p></div>
  if (!sesion) return <Cargando texto="Preparando el simulador…" />

  const cargar = (b: Backend) => b.rpc<EstadoAdmin>('admin_state', { p_session: sesion })
  return (
    <SesionContexto value={sesion}>
      <ServidorProvider backend={backend} cargar={cargar} plazo={plazoDelJuego}>
        <Mesa />
      </ServidorProvider>
    </SesionContexto>
  )
}

function Mesa() {
  const { estado } = useServidor<EstadoAdmin>()
  if (!estado) return <Cargando texto="Abriendo la mesa…" />
  const listo = estado.event.rehearsal && estado.players.length >= 4
  return listo ? <Simulacion /> : <Preparar />
}

/** Un solo formulario deja la noche lista: bots, secretos aprobados, la puerta abierta y tú ya adentro. */
function Preparar() {
  const { backend, sesion, refrescar } = useAdmin()
  const avisar = useAvisos()
  const [nombre, setNombre] = useState('Tú')
  const [bots, setBots] = useState(11)
  const [trabajando, setTrabajando] = useState(false)

  const preparar = async (ev: FormEvent) => {
    ev.preventDefault()
    setTrabajando(true)
    try {
      await backend.rpc('admin_config', {
        p_session: sesion,
        p_changes: {
          rehearsal: true,
          // Tiempos cortos para recorrer una noche entera en unos minutos.
          round_seconds: 90, vote_seconds: 60, tiebreak_seconds: 30, kill_seconds: 45, pause_seconds: 15, bots_delay_seconds: 5,
          address: 'Calle Falsa 123, Col. Roma Norte, CDMX',
        },
      })
      const token = nuevoToken()
      guardarToken(token)
      // Antes que nada: en cuanto haya bots, la mesa se pinta y necesita saber cuál es tu teléfono.
      sessionStorage.setItem('mariela.sim.token', token)
      await backend.rpc('rsvp', { p_token: token, p_name: nombre.trim() || 'Tú', p_about: 'Mariela', p_text: 'Se sabe de memoria todas las temporadas de Gossip Girl.' })
      await backend.rpc('admin_rehearsal', { p_session: sesion, p_action: 'bots', p_value: bots })
      await backend.rpc('admin_approve_all', { p_session: sesion })
      await backend.rpc('admin_phase', { p_session: sesion, p_phase: 'lobby' })
      await backend.rpc('check_in', { p_token: token, p_code: null })
      await refrescar()
    } catch (e) {
      avisar(mensajeDe(e), 'error')
    }
    setTrabajando(false)
  }

  return (
    <div className="juego">
      <div className="bruma" aria-hidden="true" />
      <main className="j-escena">
        <form className="j-pantalla sim-preparar" onSubmit={preparar}>
          <Cera className="cargando-sello" />
          <p className="j-etiqueta">Simulador</p>
          <h1 className="j-titulo">Prueba la noche entera, sin nadie más.</h1>
          <p className="j-texto">
            Te doy un teléfono, la tele y los controles del admin. Los demás invitados son bots que votan y matan solos, y el reloj se puede adelantar. Todo corre en tu navegador con el mismo motor que usará la fiesta.
          </p>
          <div className="campo sim-campo">
            <label htmlFor="sim-nombre">¿Cómo te llamas en la fiesta?</label>
            <input id="sim-nombre" value={nombre} maxLength={40} onChange={ev => setNombre(ev.target.value)} />
          </div>
          <div className="campo sim-campo">
            <label htmlFor="sim-bots">¿Cuántos bots?</label>
            <select id="sim-bots" value={bots} onChange={ev => setBots(Number(ev.target.value))}>
              {[5, 8, 11, 15, 19].map(n => (
                <option key={n} value={n}>
                  {n} bots ({n + 1} jugadores)
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="primario" disabled={trabajando}>
            {trabajando ? 'Preparando…' : 'Preparar la noche'}
          </button>
          <a className="j-enlace" href="/">
            Volver a la invitación
          </a>
        </form>
      </main>
    </div>
  )
}

const ATAJOS = [
  { texto: '+30 s', seg: 30 },
  { texto: '+1 min', seg: 60 },
  { texto: '+5 min', seg: 300 },
]

function Simulacion() {
  const { a, actuar, backend } = useAdmin()
  const [tokenTu] = useState(() => sessionStorage.getItem('mariela.sim.token'))
  const ev = a.event
  const g = a.game
  const r = g?.round ?? null
  const activa = Boolean(g && !g.ended && ev.phase === 'jugando')
  const pausado = Boolean(ev.paused_at)
  const jugadores = a.players

  const estadoTexto = !g
    ? ev.phase === 'lobby'
      ? 'Puerta abierta · listos para repartir'
      : ev.phase === 'fin'
        ? 'La noche terminó'
        : 'Invitación'
    : g.ended
      ? `Partida ${g.number} terminada`
      : `Partida ${g.number} · ronda ${r?.number} · ${r?.state}`

  return (
    <div className="juego sim">
      <div className="bruma" aria-hidden="true" />
      <header className="sim-barra">
        <div className="sim-titulo">
          <Cera className="sim-sello" />
          <div>
            <b>Simulador</b>
            <span>{estadoTexto}{pausado ? ' · en pausa' : ''}</span>
          </div>
        </div>
        <div className="sim-controles">
          {(ev.phase === 'lobby' || (ev.phase === 'jugando' && !activa)) && (
            <button type="button" className="primario" id="sim-repartir" onClick={() => void actuar('admin_deal', { p_force: false }, 'Cartas repartidas.')}>
              Repartir cartas
            </button>
          )}
          {activa && (
            <>
              <button type="button" className="secundario" onClick={() => void actuar('admin_control', { p_action: 'force' })} disabled={pausado}>
                Adelantar ▸
              </button>
              <button type="button" className="secundario" onClick={() => void actuar('admin_control', { p_action: pausado ? 'resume' : 'pause' })}>
                {pausado ? 'Reanudar' : 'Pausar'}
              </button>
            </>
          )}
          {ATAJOS.map(x => (
            <button key={x.seg} type="button" className="secundario" onClick={() => void actuar('admin_rehearsal', { p_action: 'advance', p_value: x.seg })}>
              {x.texto}
            </button>
          ))}
          {ev.phase === 'jugando' && (
            <button type="button" className="secundario peligro" onClick={() => void actuar('admin_control', { p_action: 'end_night' }, 'La noche terminó.')}>
              Terminar la noche
            </button>
          )}
          {ev.phase === 'fin' && (
            <button type="button" className="secundario" onClick={() => void actuar('admin_control', { p_action: 'reopen' })}>
              Reabrir
            </button>
          )}
          <button
            type="button"
            className="secundario peligro"
            onClick={async () => {
              if (!confirm('¿Reiniciar el ensayo? Se borran las partidas y los bots.')) return
              await actuar('admin_rehearsal', { p_action: 'reset' }, 'Ensayo reiniciado.')
            }}
          >
            Reiniciar
          </button>
        </div>
      </header>

      <div className="sim-mesa">
        <Telefono etiqueta="Teléfono A" jugadores={jugadores} inicial={tokenTu ? 'tu' : 'nuevo'} tokenTu={tokenTu} />
        <Telefono etiqueta="Teléfono B" jugadores={jugadores} inicial={jugadores.find(p => p.bot)?.id ?? 'nuevo'} tokenTu={tokenTu} />
        <div className="sim-lado">
          <Tele tvKey={ev.tv_key} />
          <PanelAdmin />
        </div>
      </div>
      <p className="sim-pie">
        <button type="button" className="j-enlace" onClick={() => void backend.rpc('advance')}>
          Empujar el reloj
        </button>
        <a className="j-enlace" href="/">
          Ver la invitación
        </a>
        <a className="j-enlace" href="/admin">
          Panel de admin
        </a>
      </p>
    </div>
  )
}

type Opcion = 'tu' | 'nuevo' | string

function Telefono({ etiqueta, jugadores, inicial, tokenTu }: { etiqueta: string; jugadores: EstadoAdmin['players']; inicial: Opcion; tokenTu: string | null }) {
  const { actuar } = useAdmin()
  const [opcion, setOpcion] = useState<Opcion>(inicial)
  const [token, setToken] = useState<string | null>(opcion === 'tu' ? tokenTu : null)
  const pedido = useRef(0)

  // Cada vez que se elige a alguien, el servidor le da un token nuevo y el iframe se recarga como esa persona.
  useEffect(() => {
    const id = ++pedido.current
    if (opcion === 'tu') {
      setToken(tokenTu)
      return
    }
    if (opcion === 'nuevo') {
      setToken('')
      return
    }
    void actuar<{ token: string }>('admin_rehearsal', { p_action: 'impersonate', p_player: opcion }).then(r => {
      if (r && id === pedido.current) setToken(r.token)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opcion, tokenTu])

  const src = token === null ? undefined : `/?como=${encodeURIComponent(token)}`
  return (
    <section className="sim-telefono">
      <label className="sim-selector">
        <span>{etiqueta}</span>
        <select value={opcion} onChange={ev => setOpcion(ev.target.value)}>
          {tokenTu && <option value="tu">Tú</option>}
          <option value="nuevo">Alguien sin responder</option>
          <optgroup label="Invitados">
            {jugadores.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.bot ? ' (bot)' : ''}
              </option>
            ))}
          </optgroup>
        </select>
      </label>
      <div className="sim-marco">{src ? <iframe key={src} title={etiqueta} src={src} /> : <Cargando texto="…" />}</div>
    </section>
  )
}

function Tele({ tvKey }: { tvKey: string }) {
  const caja = useRef<HTMLDivElement>(null)
  const [escala, setEscala] = useState(0.4)
  useEffect(() => {
    const el = caja.current
    if (!el) return
    const medir = () => setEscala(el.clientWidth / 1920)
    medir()
    const obs = new ResizeObserver(medir)
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return (
    <section className="sim-tele">
      <p className="j-subetiqueta">La tele</p>
      <div ref={caja} className="sim-tele-caja" style={{ height: `${1080 * escala}px` }}>
        <iframe title="La tele" src={`/tv#k=${tvKey}`} style={{ transform: `scale(${escala})` }} />
      </div>
    </section>
  )
}

function PanelAdmin() {
  const [abierto, setAbierto] = useState(false)
  const url = useMemo(() => '/admin', [])
  return (
    <section className="sim-admin">
      <button type="button" className="j-enlace" aria-expanded={abierto} onClick={() => setAbierto(v => !v)}>
        {abierto ? 'Ocultar el panel de admin' : 'Mostrar el panel de admin'}
      </button>
      {abierto && (
        <div className="sim-admin-caja">
          <iframe title="Panel de admin" src={url} />
        </div>
      )}
    </section>
  )
}
