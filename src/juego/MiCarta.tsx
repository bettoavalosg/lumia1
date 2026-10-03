import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import dorso from '../invitacion/svg/dorso.svg?raw'
import { vibrar } from '../lib/movimiento'
import { lista, nombres, useJuego } from '../servidor/hooks'
import type { Rol } from '../servidor/tipos'
import { CaraCarta } from './CaraCarta'

/** Tu carta: boca abajo hasta que la mantienes presionada. Al soltar, se esconde sola. */
export function MiCarta() {
  const { game, me } = useJuego()
  const activa = Boolean(game && !game.ended && me.in_game && me.role)
  if (!activa || !me.role) {
    const texto = !game
      ? 'Todavía no hay cartas. Cuando Mariela reparta, la tuya aparece aquí.'
      : game.ended
        ? 'Las cartas de esta partida ya se revelaron. En un momento hay nuevas.'
        : 'Esta partida empezó sin ti. En la siguiente te toca carta.'
    return (
      <section className="j-pantalla j-carta">
        <h1 className="sr-only">Mi carta</h1>
        <p className="j-etiqueta" aria-hidden="true">
          Mi carta
        </p>
        <div className="carta-mano quieta" aria-hidden="true">
          <span className="cm-giro">
            <span className="cm-cara cm-dorso" dangerouslySetInnerHTML={{ __html: `<svg class="cara-svg" viewBox="0 0 280 480" focusable="false">${dorso}</svg>` }} />
          </span>
        </div>
        <p className="j-texto">{texto}</p>
      </section>
    )
  }
  return <CartaSecreta rol={me.role} complices={nombres(me.accomplices)} muerto={me.alive === false} />
}

function CartaSecreta({ rol, complices, muerto }: { rol: Rol; complices: string[]; muerto: boolean }) {
  const [viendo, setViendo] = useState(false)
  const [montada, setMontada] = useState(false)
  const espera = useRef<number | undefined>(undefined)

  // La cara solo existe en el DOM mientras se ve (y un instante más, para el giro de regreso).
  const soltar = () => {
    clearTimeout(espera.current)
    setViendo(false)
  }
  const empezar = () => {
    clearTimeout(espera.current)
    // Un roce no la voltea: hay que mantenerla un momento. Así un dedo perdido no delata nada.
    espera.current = window.setTimeout(() => {
      setMontada(true)
      requestAnimationFrame(() => setViendo(true))
      vibrar(12)
    }, 170)
  }

  useEffect(() => {
    if (viendo || !montada) return
    const id = setTimeout(() => setMontada(false), 450)
    return () => clearTimeout(id)
  }, [viendo, montada])

  useEffect(() => {
    const esconder = () => {
      clearTimeout(espera.current)
      setViendo(false)
    }
    const alCambiar = () => document.hidden && esconder()
    window.addEventListener('blur', esconder)
    document.addEventListener('visibilitychange', alCambiar)
    return () => {
      clearTimeout(espera.current)
      window.removeEventListener('blur', esconder)
      document.removeEventListener('visibilitychange', alCambiar)
    }
  }, [])

  const alPresionar = (ev: PointerEvent<HTMLButtonElement>) => {
    if (ev.button !== 0) return
    ev.currentTarget.setPointerCapture(ev.pointerId)
    empezar()
  }
  const alTeclear = (ev: KeyboardEvent<HTMLButtonElement>) => {
    if ((ev.key === ' ' || ev.key === 'Enter') && !ev.repeat) {
      ev.preventDefault()
      empezar()
    }
  }
  const alSoltarTecla = (ev: KeyboardEvent<HTMLButtonElement>) => {
    if (ev.key === ' ' || ev.key === 'Enter') soltar()
  }

  return (
    <section className="j-pantalla j-carta">
      <h1 className="sr-only">Mi carta</h1>
      <p className="j-etiqueta" aria-hidden="true">
        Mi carta
      </p>
      <button
        type="button"
        id="mi-carta"
        className={`carta-mano${viendo ? ' volteada' : ''}${muerto ? ' apagada' : ''}`}
        aria-label="Mantén presionado para ver tu carta"
        onPointerDown={alPresionar}
        onPointerUp={soltar}
        onPointerCancel={soltar}
        onLostPointerCapture={soltar}
        onKeyDown={alTeclear}
        onKeyUp={alSoltarTecla}
        onBlur={soltar}
        onContextMenu={ev => ev.preventDefault()}
      >
        <span className="cm-giro">
          <span className="cm-cara cm-dorso" aria-hidden="true" dangerouslySetInnerHTML={{ __html: `<svg class="cara-svg" viewBox="0 0 280 480" focusable="false">${dorso}</svg>` }} />
          <span className="cm-cara cm-frente" aria-hidden="true">
            {montada && <CaraCarta rol={rol} />}
          </span>
        </span>
      </button>
      <p className="j-nota" aria-live="polite" id="mi-carta-nota">
        {viendo ? (rol === 'asesino' ? 'Eres el asesino.' : 'Eres inocente.') : 'Mantén presionado para verla. Al soltar, se esconde.'}
      </p>
      {viendo && rol === 'asesino' && complices.length > 0 && <p className="j-texto">Tu cómplice: {lista(complices)}.</p>}
      {!viendo && <p className="j-texto chico">No se la enseñes a nadie. Ni siquiera a quien te caiga bien.</p>}
    </section>
  )
}
