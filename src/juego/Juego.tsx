import { useEffect, useRef, useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { SinConexion } from '../compartido/SinConexion'
import { vibrar } from '../lib/movimiento'
import { leerSesion, guardarSesion } from '../lib/sesion'
import { useJuego } from '../servidor/hooks'
import type { Estado } from '../servidor/tipos'
import { Bitacora } from './Bitacora'
import { IconoBitacora, IconoCarta, IconoNoche } from './iconos'
import { MiCarta } from './MiCarta'
import { Muerte } from './Muerte'
import { Noche } from './Noche'
import '../styles/juego.css'

type Pestana = 'noche' | 'carta' | 'bitacora'
const PESTANAS: { id: Pestana; texto: string; icono: () => React.JSX.Element }[] = [
  { id: 'noche', texto: 'Noche', icono: IconoNoche },
  { id: 'carta', texto: 'Mi carta', icono: IconoCarta },
  { id: 'bitacora', texto: 'Bitácora', icono: IconoBitacora },
]

/** Avisa (con un aviso y una vibración) cuando el juego cambia de momento estando en la app. */
function useAvisosDeCambios(e: Estado) {
  const avisar = useAvisos()
  const previo = useRef<Estado | null>(null)
  useEffect(() => {
    const antes = previo.current
    previo.current = e
    if (!antes) return
    const g = e.game
    const ga = antes.game
    const r = g?.round
    const ra = ga?.round
    if (g && g.number !== ga?.number) {
      vibrar([40, 50, 40])
      avisar('Cartas repartidas. Mira la tuya.', 'ok')
      return
    }
    if (r && ra && r.id === ra.id && r.state !== ra.state) {
      if (r.state === 'votacion') {
        vibrar([60, 50, 60])
        avisar('Se abrió la votación.')
      } else if (r.state === 'desempate') {
        vibrar([60, 50, 60])
        avisar('Empate. Desempate relámpago.')
      } else if (r.state === 'veredicto') {
        vibrar(90)
        avisar('Ya hay veredicto.')
      }
    } else if (r && ra && r.id !== ra.id && r.number > ra.number) {
      avisar(`Empieza la ronda ${r.number}.`)
    }
    if (g?.last_kill && g.last_kill.at !== ga?.last_kill?.at && g.last_kill.victim.id !== e.me?.id) {
      avisar(`${g.last_kill.victim.name} ha muerto.`)
    }
    if (antes.me?.alive && e.me?.alive === false) vibrar([200, 80, 200])
  }, [e, avisar])
}

export default function Juego({ alVerInvitacion }: { alVerInvitacion: () => void }) {
  const { e, me, game, pausadoEn } = useJuego()
  const [pestana, setPestana] = useState<Pestana>('noche')
  useAvisosDeCambios(e)

  // "Has muerto" se muestra una vez por partida.
  const claveMuerte = game ? `mariela.muerte.${game.id}` : null
  const [vista, setVista] = useState(() => (claveMuerte ? leerSesion(claveMuerte) === '1' : false))
  useEffect(() => {
    setVista(claveMuerte ? leerSesion(claveMuerte) === '1' : false)
  }, [claveMuerte])
  const muerte = Boolean(game && !game.ended && me.in_game && me.alive === false && !vista)

  const estado = !game || !me.in_game ? 'En la lista' : me.alive === false ? 'Sin vida' : 'Con vida'

  return (
    <div className="juego" data-pestana={pestana}>
      <div className="bruma" aria-hidden="true" />
      <header className="j-barra">
        <svg className="j-blason" viewBox="0 0 80 80" aria-hidden="true" focusable="false">
          <use href="#blason" />
        </svg>
        <span className="j-quien">{me.name}</span>
        <span className={`j-estado ${me.alive === false ? 'muerto' : me.in_game ? 'vivo' : ''}`}>{estado}</span>
      </header>

      <SinConexion />

      {pausadoEn && (
        <p className="j-pausa" role="status">
          <b>Pausa.</b> El tiempo está detenido.
        </p>
      )}

      <main className="j-escena" id="escena-juego">
        {pestana === 'noche' && <Noche alVerInvitacion={alVerInvitacion} irACarta={() => setPestana('carta')} />}
        {pestana === 'carta' && <MiCarta />}
        {pestana === 'bitacora' && <Bitacora />}
      </main>

      <nav className="j-pestanas" aria-label="Secciones">
        {PESTANAS.map(({ id, texto, icono: Icono }) => (
          <button key={id} type="button" aria-current={pestana === id ? 'page' : undefined} onClick={() => setPestana(id)}>
            <Icono />
            <span>{texto}</span>
          </button>
        ))}
      </nav>

      {muerte && (
        <Muerte
          alCerrar={() => {
            if (claveMuerte) guardarSesion(claveMuerte, '1')
            setVista(true)
          }}
        />
      )}
    </div>
  )
}
