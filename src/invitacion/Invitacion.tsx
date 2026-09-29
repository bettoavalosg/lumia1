import { useEffect, useState } from 'react'
import { clases } from '../lib/clases'
import { Escena } from './Escena'
import { Revelador } from './Revelar'
import { Suite } from './Suite'
import sprite from './svg/sprite.svg?raw'

/** Una mesa a oscuras bajo luz de vela: el sobre, la suite de tarjetas y la carta de tarot. */
export function Invitacion() {
  const [encendida, setEncendida] = useState(false)
  const [abierta, setAbierta] = useState(false)

  // Al cargar, la luz se enciende.
  useEffect(() => {
    const cuadro = requestAnimationFrame(() => setEncendida(true))
    return () => cancelAnimationFrame(cuadro)
  }, [])

  return (
    <div className={clases('invitacion', encendida && 'encendida')}>
      <svg className="sprite" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: sprite }} />
      <div className="bruma" aria-hidden="true" />
      <div className="apagon" aria-hidden="true" />
      <main id="carta">
        <Escena onAbierta={() => setAbierta(true)} />
        <Revelador activo={abierta}>
          <Suite abierta={abierta} />
        </Revelador>
      </main>
    </div>
  )
}
