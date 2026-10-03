import type { Persona } from '../servidor/tipos'
import { IconoPalomita } from './iconos'

interface Props {
  personas: Persona[]
  elegido: string | null
  alElegir: (id: string) => void
  /** Para lectores de pantalla: qué significa elegir a alguien aquí. */
  verbo: string
}

/** La rejilla de nombres: cada uno es una ficha de cartulina que se levanta al tocarla. */
export function Fichas({ personas, elegido, alElegir, verbo }: Props) {
  return (
    <ul className="j-fichas">
      {personas.map((p, i) => (
        <li key={p.id} style={{ '--i': Math.min(i, 20) }}>
          <button type="button" className="j-ficha" aria-pressed={elegido === p.id} aria-label={`${verbo} ${p.name}`} onClick={() => alElegir(p.id)}>
            <span className="j-ficha-nombre">{p.name}</span>
            <span className="j-ficha-marca" aria-hidden="true">
              <IconoPalomita />
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
