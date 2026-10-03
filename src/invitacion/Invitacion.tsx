import { useEffect, useMemo, useState } from 'react'
import { clases } from '../lib/clases'
import { guardarLocal, leerLocal } from '../lib/almacen'
import { Escena } from './Escena'
import { Revelador } from './Revelar'
import { Suite } from './Suite'

interface Props {
  /** Quien ya está en la noche vuelve a la invitación desde el juego y puede regresar. */
  alVolver?: () => void
  /** Cierra la invitación y entra al juego (se ofrece cuando la puerta ya está abierta). */
  alEntrar?: () => void
  alCeremonia?: (enCurso: boolean) => void
}

/** Una mesa a oscuras bajo luz de vela: el sobre, la suite de tarjetas y la carta de tarot. */
export function Invitacion({ alVolver, alEntrar, alCeremonia }: Props) {
  const [encendida, setEncendida] = useState(false)
  const [abierta, setAbierta] = useState(false)
  const yaAbierta = useMemo(() => leerLocal('mariela.sobre') === 'abierto', [])

  // Al cargar, la luz se enciende.
  useEffect(() => {
    const cuadro = requestAnimationFrame(() => setEncendida(true))
    return () => cancelAnimationFrame(cuadro)
  }, [])

  return (
    <div className={clases('invitacion', encendida && 'encendida')}>
      <div className="bruma" aria-hidden="true" />
      <div className="apagon" aria-hidden="true" />
      {alVolver && abierta && (
        <button type="button" className="volver-noche" onClick={alVolver}>
          ← Volver a la noche
        </button>
      )}
      <main id="carta">
        <Escena
          yaAbierta={yaAbierta}
          onAbierta={() => {
            setAbierta(true)
            guardarLocal('mariela.sobre', 'abierto')
          }}
        />
        <Revelador activo={abierta}>
          <Suite abierta={abierta} alEntrar={alEntrar} alCeremonia={alCeremonia} />
        </Revelador>
      </main>
    </div>
  )
}
