import { useEffect, useState, type FormEvent } from 'react'
import { Cargando } from '../compartido/Cargando'
import { SinConexion } from '../compartido/SinConexion'
import { Cera } from '../compartido/Sprite'
import type { Backend } from '../servidor/backend'
import { useBackend } from '../servidor/BackendContexto'
import { mensajeDe } from '../servidor/errores'
import { plazoDelJuego } from '../servidor/hooks'
import { sesionAdmin } from '../servidor/identidad'
import { ServidorProvider, useServidor } from '../servidor/Servidor'
import type { EstadoAdmin } from '../servidor/tipos'
import '../styles/juego.css'
import '../styles/admin.css'
import { Ajustes } from './Ajustes'
import { SesionContexto, useAdmin } from './comun'
import { Ensayo } from './Ensayo'
import { Invitados } from './Invitados'
import { Noche } from './Noche'
import { Secretos } from './Secretos'

export default function Admin() {
  const backend = useBackend()
  const [sesion, setSesion] = useState<string | null>(() => sesionAdmin.leer())
  if (!sesion) return <Acceso alEntrar={setSesion} />
  const cargar = (b: Backend) => b.rpc<EstadoAdmin>('admin_state', { p_session: sesion })
  return (
    <SesionContexto value={sesion}>
      <ServidorProvider backend={backend} cargar={cargar} plazo={plazoDelJuego}>
        <Panel alSalir={() => setSesion(null)} />
      </ServidorProvider>
    </SesionContexto>
  )
}

function Acceso({ alEntrar }: { alEntrar: (sesion: string) => void }) {
  const backend = useBackend()
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  const entrar = async (ev: FormEvent) => {
    ev.preventDefault()
    setError('')
    setEnviando(true)
    try {
      const r = await backend.rpc<{ ok: boolean; session?: string; expires_at?: string; message?: string }>('admin_login', { p_pin: pin })
      if (r.ok && r.session && r.expires_at) {
        sesionAdmin.guardar(r.session, r.expires_at)
        alEntrar(r.session)
        return
      }
      setError(r.message ?? 'No se pudo entrar.')
      setPin('')
    } catch (e) {
      setError(mensajeDe(e))
    }
    setEnviando(false)
  }

  return (
    <div className="juego ad-acceso">
      <div className="bruma" aria-hidden="true" />
      <main className="j-escena">
        <form className="j-pantalla" onSubmit={entrar}>
          <Cera className="cargando-sello" />
          <p className="j-etiqueta">Admin</p>
          <h1 className="j-titulo">¿Quién manda esta noche?</h1>
          <div className="campo ad-pin">
            <label htmlFor="pin">PIN</label>
            <input
              id="pin"
              type="password"
              inputMode="text"
              autoComplete="current-password"
              autoFocus
              value={pin}
              onChange={ev => setPin(ev.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby="pin-error"
            />
          </div>
          <p className="error" id="pin-error" role="alert">
            {error}
          </p>
          {backend.modo === 'demo' && <p className="j-nota">Modo demo: el PIN es 000000.</p>}
          <button type="submit" className="primario" disabled={enviando || pin.length < 1}>
            {enviando ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </main>
    </div>
  )
}

type Pestana = 'noche' | 'invitados' | 'secretos' | 'ajustes' | 'ensayo'

function Panel({ alSalir }: { alSalir: () => void }) {
  const { estado, error } = useServidor<EstadoAdmin>()
  const [pestana, setPestana] = useState<Pestana>('noche')

  // Si la sesión venció (o se cambió el PIN), se vuelve a pedir.
  useEffect(() => {
    if (error?.codigo === 'sin_permiso') {
      sesionAdmin.borrar()
      alSalir()
    }
  }, [error, alSalir])

  if (!estado) return <Cargando texto="Abriendo el panel…" sinRed={Boolean(error)} />
  return <Contenido pestana={pestana} setPestana={setPestana} alSalir={alSalir} />
}

function Contenido({ pestana, setPestana, alSalir }: { pestana: Pestana; setPestana: (p: Pestana) => void; alSalir: () => void }) {
  const { a, backend, sesion } = useAdmin()
  const secretosPendientes = a.secrets.filter(s => s.status === 'pendiente').length
  const pestanas: { id: Pestana; texto: string; aviso?: number }[] = [
    { id: 'noche', texto: 'Noche' },
    { id: 'invitados', texto: 'Invitados' },
    { id: 'secretos', texto: 'Secretos', aviso: secretosPendientes },
    { id: 'ajustes', texto: 'Ajustes' },
    ...(a.event.rehearsal ? [{ id: 'ensayo' as const, texto: 'Ensayo' }] : []),
  ]
  const fases = { invitacion: 'Invitación', lobby: 'Puerta abierta', jugando: 'Jugando', fin: 'Terminó' }

  return (
    <div className="juego admin">
      <div className="bruma" aria-hidden="true" />
      <header className="j-barra">
        <svg className="j-blason" viewBox="0 0 80 80" aria-hidden="true" focusable="false">
          <use href="#blason" />
        </svg>
        <span className="j-quien">Admin</span>
        <span className="j-estado vivo">{fases[a.event.phase]}</span>
        <button
          type="button"
          className="ad-salir"
          onClick={() => {
            void backend.rpc('admin_logout', { p_session: sesion }).catch(() => undefined)
            sesionAdmin.borrar()
            alSalir()
          }}
        >
          Salir
        </button>
      </header>
      {a.event.rehearsal && (
        <p className="ad-banda" role="status">
          Modo ensayo · el reloj se puede adelantar y hay bots
        </p>
      )}
      <SinConexion clase="ad-banda ad-conexion" />
      <nav className="ad-pestanas" aria-label="Secciones del panel">
        {pestanas.map(p => (
          <button key={p.id} type="button" aria-current={pestana === p.id ? 'page' : undefined} onClick={() => setPestana(p.id)}>
            {p.texto}
            {p.aviso ? <b className="ad-aviso">{p.aviso}</b> : null}
          </button>
        ))}
      </nav>
      <main className="ad-cuerpo">
        <h1 className="sr-only">Panel de admin</h1>
        {pestana === 'noche' && <Noche irA={setPestana} />}
        {pestana === 'invitados' && <Invitados />}
        {pestana === 'secretos' && <Secretos />}
        {pestana === 'ajustes' && <Ajustes />}
        {pestana === 'ensayo' && <Ensayo />}
      </main>
    </div>
  )
}
