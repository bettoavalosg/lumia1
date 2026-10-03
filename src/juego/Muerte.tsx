import { useEffect, useRef } from 'react'
import { Cera } from '../compartido/Sprite'

/** Has muerto. Una vez, a pantalla completa; después la app sigue, pero ya no votas. */
export function Muerte({ alCerrar }: { alCerrar: () => void }) {
  const boton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    boton.current?.focus()
  }, [])
  return (
    <div className="j-muerte" role="alertdialog" aria-modal="true" aria-labelledby="muerte-t" aria-describedby="muerte-d">
      <div className="j-muerte-sello" aria-hidden="true">
        <Cera />
        <svg viewBox="0 0 240 240" focusable="false">
          <polyline pathLength={100} points="127,0 123,16 120,32 113,50 119,65 125,84 132,96 122,111 116,126 110,142 119,156 122,172 127,187 125,205 117,222 115,240" />
        </svg>
      </div>
      <h1 id="muerte-t" className="j-titulo grande">
        Has muerto.
      </h1>
      <p id="muerte-d" className="j-texto">
        Sigues en la fiesta, pero ya no votas. Mira, calla y no delates a nadie.
      </p>
      <button ref={boton} type="button" className="secundario" onClick={alCerrar}>
        Seguir mirando
      </button>
    </div>
  )
}
