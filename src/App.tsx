import { lazy, Suspense, useState } from 'react'
import { Cargando } from './compartido/Cargando'
import { Invitacion } from './invitacion/Invitacion'
import type { Backend } from './servidor/backend'
import { useBackend } from './servidor/BackendContexto'
import { ESTADO_INICIAL, plazoDelJuego } from './servidor/hooks'
import { tokenDispositivo } from './servidor/identidad'
import { ServidorProvider, useServidor } from './servidor/Servidor'
import type { Estado } from './servidor/tipos'
import { PastillaDemo } from './demo/PastillaDemo'

const Juego = lazy(() => import('./juego/Juego'))
const FinNoche = lazy(() => import('./juego/FinNoche'))

const cargarJugador = (b: Backend) => b.rpc<Estado>('get_state', { p_token: tokenDispositivo() })

/** La ruta `/`: la invitación hasta que abre la puerta; después, la noche de cada invitado. */
export default function App() {
  const backend = useBackend()
  return (
    <ServidorProvider backend={backend} cargar={cargarJugador} plazo={plazoDelJuego} inicial={ESTADO_INICIAL}>
      <Contenido />
      <PastillaDemo />
    </ServidorProvider>
  )
}

function Contenido() {
  const { estado, cargado, error } = useServidor<Estado>()
  // Mientras se sella el secreto, la pantalla no cambia aunque el servidor ya sepa quién eres.
  const [ceremonia, setCeremonia] = useState(false)
  const [retenida, setRetenida] = useState(false)
  const [verInvitacion, setVerInvitacion] = useState(false)

  if (error?.codigo === 'demo_ocupado') {
    return (
      <div className="cargando" role="alert">
        <p>{error.message}</p>
      </div>
    )
  }
  // Quien ya tiene un lugar espera a saber en qué momento va la noche; a quien no, la invitación le aparece de inmediato.
  if (!cargado && !error && tokenDispositivo()) return <Cargando texto="Un momento…" />
  if (!estado) return <Cargando texto="Un momento…" />

  const conocido = Boolean(estado.known && estado.me)
  const fase = estado.event.phase
  const enNoche = conocido && (fase === 'lobby' || fase === 'jugando')

  if (conocido && fase === 'fin' && !verInvitacion && !retenida && !ceremonia) {
    return (
      <Suspense fallback={<Cargando />}>
        <FinNoche alVerInvitacion={() => setVerInvitacion(true)} />
      </Suspense>
    )
  }

  if (enNoche && !verInvitacion && !retenida && !ceremonia) {
    return (
      <Suspense fallback={<Cargando />}>
        <Juego alVerInvitacion={() => setVerInvitacion(true)} />
      </Suspense>
    )
  }

  // Un proyecto a medio configurar (falta pegar setup.sql, o la clave está mal) se nota desde la primera visita, no cuando falla el primer RSVP.
  const sinConfigurar = error?.codigo === 'sin_esquema' || error?.codigo === 'clave_invalida'

  return (
    <>
      <Invitacion
        alCeremonia={en => {
          setCeremonia(en)
          if (!en) return
          setRetenida(true)
        }}
        alEntrar={() => {
          setRetenida(false)
          setVerInvitacion(false)
        }}
        alVolver={conocido && (enNoche || fase === 'fin') && verInvitacion ? () => setVerInvitacion(false) : undefined}
      />
      {sinConfigurar && (
        <p className="aviso-config" role="alert">
          <b>Falta configurar el servidor.</b> {error?.message}
        </p>
      )}
    </>
  )
}
