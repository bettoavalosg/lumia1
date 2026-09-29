import { Fragment, useEffect, useState } from 'react'
import { partesRestantes, separador } from '../lib/cuenta'
import { INICIO_FIESTA } from '../lib/evento'

/** Cuenta regresiva a la fiesta. Cada número se remonta al cambiar, y así rueda (ver `.reloj .n.rueda`). */
export function Reloj() {
  const [ahora, setAhora] = useState(() => Date.now())
  const partes = partesRestantes(INICIO_FIESTA.getTime() - ahora)
  const termino = partes === null

  useEffect(() => {
    if (termino) return
    const intervalo = setInterval(() => setAhora(Date.now()), 1000)
    return () => clearInterval(intervalo)
  }, [termino])

  if (!partes) {
    return (
      <p className="reloj" id="reloj">
        Ya se puede voltear. Corre.
      </p>
    )
  }
  return (
    <p className="reloj" id="reloj">
      Se voltea en{' '}
      {partes.map((parte, i) => (
        <Fragment key={parte.clave}>
          <span key={parte.valor} className="n rueda">
            {parte.valor}
          </span>{' '}
          {parte.unidad}
          {separador(i, partes.length)}
        </Fragment>
      ))}
    </p>
  )
}
