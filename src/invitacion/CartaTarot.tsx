import { useEffect, useRef, type MouseEvent } from 'react'
import { prefiereMenosMovimiento, tienePunteroFino, vibrar } from '../lib/movimiento'
import dorso from './svg/dorso.svg?raw'

/** La carta no se deja voltear: empieza a girar hacia donde la empujaste y algo la regresa. */
export function CartaTarot({ onIntento }: { onIntento: () => void }) {
  const boton = useRef<HTMLButtonElement>(null)
  const giro = useRef<HTMLSpanElement>(null)
  const cuerpo = useRef<HTMLSpanElement>(null)
  const resistencia = useRef<Animation | null>(null)

  // Con mouse, la carta se inclina hacia el cursor y el brillo del grabado lo sigue.
  useEffect(() => {
    const b = boton.current
    const c = cuerpo.current
    if (!b || !c || !tienePunteroFino() || prefiereMenosMovimiento()) return
    const fijar = (rx: string, ry: string, mx: string) => {
      c.style.setProperty('--rx', rx)
      c.style.setProperty('--ry', ry)
      c.style.setProperty('--mx', mx)
    }
    const mover = (e: PointerEvent) => {
      const r = b.getBoundingClientRect()
      const x = (e.clientX - r.left) / r.width - 0.5
      const y = (e.clientY - r.top) / r.height - 0.5
      c.classList.add('inclinando')
      fijar(`${-y * 16}deg`, `${x * 16}deg`, `${(x + 0.5) * 100}%`)
    }
    const soltar = () => {
      c.classList.remove('inclinando')
      fijar('0deg', '0deg', '50%')
    }
    b.addEventListener('pointermove', mover)
    b.addEventListener('pointerleave', soltar)
    b.addEventListener('pointercancel', soltar)
    return () => {
      b.removeEventListener('pointermove', mover)
      b.removeEventListener('pointerleave', soltar)
      b.removeEventListener('pointercancel', soltar)
    }
  }, [])

  const intentar = (e: MouseEvent<HTMLButtonElement>) => {
    onIntento()
    vibrar(8)
    if (prefiereMenosMovimiento()) {
      cuerpo.current?.animate([{ opacity: 0.72 }, { opacity: 1 }], { duration: 240, easing: 'ease' })
      return
    }
    // No reinicia a medio giro: se siente como una carta que se resiste, no como un parpadeo.
    const actual = resistencia.current
    if (actual?.playState === 'running' && Number(actual.currentTime) < 430) return
    const r = e.currentTarget.getBoundingClientRect()
    const lado = e.detail && e.clientX ? (e.clientX >= r.left + r.width / 2 ? 1 : -1) : 1
    const a = 34 * lado
    resistencia.current =
      giro.current?.animate(
        [
          { transform: 'rotateY(0deg)', easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
          { transform: `rotateY(${a}deg)`, offset: 0.26, easing: 'ease-in-out' },
          { transform: `rotateY(${a * 0.85}deg)`, offset: 0.36, easing: 'ease-in-out' },
          { transform: `rotateY(${a * 0.94}deg)`, offset: 0.44, easing: 'cubic-bezier(0.77, 0, 0.175, 1)' },
          { transform: `rotateY(${a * -0.18}deg)`, offset: 0.74, easing: 'ease-in-out' },
          { transform: `rotateY(${a * 0.05}deg)`, offset: 0.88, easing: 'ease-out' },
          { transform: 'rotateY(0deg)' },
        ],
        { duration: 720 },
      ) ?? null
  }

  return (
    <button ref={boton} id="carta-juego" className="carta-juego" type="button" aria-describedby="reloj" onClick={intentar}>
      <span ref={giro} className="carta-giro">
        <span ref={cuerpo} className="carta-cuerpo">
          <svg className="dorso" viewBox="0 0 280 480" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: dorso }} />
        </span>
      </span>
      <span className="sr-only">Intentar voltear tu carta</span>
    </button>
  )
}
