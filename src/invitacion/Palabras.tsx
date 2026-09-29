import { Fragment } from 'react'

/** Parte una frase en palabras para que aparezcan una por una (ver `.palabras` en invitacion.css). */
export function Palabras({ texto }: { texto: string }) {
  return texto
    .trim()
    .split(/\s+/)
    .map((palabra, i) => (
      <Fragment key={i}>
        {i > 0 && ' '}
        <span className="p" style={{ '--i': i }}>
          {palabra}
        </span>
      </Fragment>
    ))
}
