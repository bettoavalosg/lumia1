import { useEffect, useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { mensajeDe } from '../servidor/errores'
import { useJuego } from '../servidor/hooks'
import { tokenDispositivo } from '../servidor/identidad'
import { IconoCampana, IconoCompartir } from './iconos'
import { activarPush, desactivarPush, esIos, esStandalone, pushDisponible } from './push'

interface EventoInstalacion extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

/** Instalar la app y activar los avisos: las dos cosas que hacen que la noche no se pierda por tener el teléfono bloqueado. */
export function Instalar() {
  const { backend, me, refrescar } = useJuego()
  const avisar = useAvisos()
  const [instalacion, setInstalacion] = useState<EventoInstalacion | null>(null)
  const [trabajando, setTrabajando] = useState(false)
  const standalone = esStandalone()
  const ios = esIos()

  useEffect(() => {
    const alPreguntar = (e: Event) => {
      e.preventDefault()
      setInstalacion(e as EventoInstalacion)
    }
    window.addEventListener('beforeinstallprompt', alPreguntar)
    return () => window.removeEventListener('beforeinstallprompt', alPreguntar)
  }, [])

  const instalar = async () => {
    if (!instalacion) return
    await instalacion.prompt()
    await instalacion.userChoice
    setInstalacion(null)
  }

  const alternarAvisos = async () => {
    const token = tokenDispositivo()
    if (!token) return
    setTrabajando(true)
    try {
      if (me.push) {
        await desactivarPush(backend, token)
        avisar('Avisos apagados.')
      } else {
        const r = await activarPush(backend, token)
        if (r === 'denegado') avisar('El navegador bloqueó los avisos. Actívalos en los ajustes del sitio.', 'error')
        else if (r === 'ok') avisar('Listo. Te avisamos cuando pase algo.', 'ok')
      }
      await refrescar()
    } catch (e) {
      avisar(mensajeDe(e), 'error')
    }
    setTrabajando(false)
  }

  const puedeAvisos = pushDisponible() && (!ios || standalone)
  const necesitaInstalarPrimero = pushDisponible() && ios && !standalone

  if (standalone && !puedeAvisos) return null
  if (!instalacion && !ios && !puedeAvisos) return null

  return (
    <section className="j-herramientas" aria-label="Instalar y avisos">
      {!standalone && instalacion && (
        <button type="button" className="j-herramienta" onClick={() => void instalar()}>
          <IconoCompartir />
          <span>
            <b>Instala la app</b>
            <small>Se abre más rápido y no se pierde entre pestañas.</small>
          </span>
        </button>
      )}
      {!standalone && ios && (
        <div className="j-herramienta pasiva">
          <IconoCompartir />
          <span>
            <b>Instala la app</b>
            <small>Toca Compartir y luego “Agregar a inicio”. Solo así te pueden llegar avisos en iPhone.</small>
          </span>
        </div>
      )}
      {puedeAvisos && (
        <button type="button" className="j-herramienta" onClick={() => void alternarAvisos()} disabled={trabajando} aria-pressed={me.push}>
          <IconoCampana />
          <span>
            <b>{me.push ? 'Avisos activados' : 'Activa los avisos'}</b>
            <small>{me.push ? 'Toca para apagarlos.' : 'Te decimos cuando abra la votación o alguien caiga.'}</small>
          </span>
        </button>
      )}
      {necesitaInstalarPrimero && <p className="j-nota chica">Instálala primero y luego activa los avisos desde la app.</p>}
    </section>
  )
}
