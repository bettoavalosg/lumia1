import { useEffect, useRef, useState } from 'react'
import { clases } from '../lib/clases'
import { EASE_IN_OUT, EASE_LENTO, EASE_OUT, prefiereMenosMovimiento, tienePunteroFino, vibrar } from '../lib/movimiento'
import { Palabras } from './Palabras'

type Fase = 'cargando' | 'listo' | 'abriendo' | 'abierta'

const GRIETA =
  '127.2,0.0 122.7,15.9 119.9,32.4 112.8,50.4 119.3,64.7 125.0,83.5 132.0,96.0 122.1,110.9 115.8,125.5 110.4,141.6 119.4,155.8 122.3,171.5 127.2,187.2 124.7,204.5 117.0,222.0 115.2,240.0'
const MIGAS = 7

/** El sobre sobre la mesa: llega, se rompe el sello, sale la portada y el sobre se retira. */
export function Escena({ onAbierta, yaAbierta = false }: { onAbierta: () => void; yaAbierta?: boolean }) {
  // Quien ya abrió el sobre en este teléfono no tiene que romper el sello otra vez.
  const [fase, setFase] = useState<Fase>(yaAbierta ? 'abierta' : 'cargando')
  const [presionando, setPresionando] = useState(false)
  const escena = useRef<HTMLElement>(null)
  const camara = useRef<HTMLDivElement>(null)
  const portada = useRef<HTMLElement>(null)
  const titulo = useRef<HTMLHeadingElement>(null)
  const sello = useRef<HTMLButtonElement>(null)
  const solapaCara = useRef<HTMLDivElement>(null)
  const solapaForro = useRef<HTMLDivElement>(null)
  const migas = useRef<(HTMLSpanElement | null)[]>([])
  const animaciones = useRef<Animation[]>([])
  const temporizadores = useRef<number[]>([])

  const listo = fase !== 'cargando'
  const abriendo = fase === 'abriendo' || fase === 'abierta'
  const abierta = fase === 'abierta'

  // El sello se estampa cuando su tipografía ya cargó, para no ver la M cambiar de fuente.
  useEffect(() => {
    let vivo = true
    Promise.race([document.fonts.load('italic 600 76px "Bodoni Moda"'), new Promise(r => setTimeout(r, 1200))])
      .catch(() => undefined)
      .then(() => requestAnimationFrame(() => vivo && setFase(f => (f === 'cargando' ? 'listo' : f))))
    return () => {
      vivo = false
    }
  }, [])

  // Sin scroll mientras el sobre está cerrado.
  useEffect(() => {
    if (abierta) return
    const raiz = document.documentElement
    raiz.style.overflow = 'hidden'
    return () => {
      raiz.style.overflow = ''
    }
  }, [abierta])

  useEffect(() => () => temporizadores.current.forEach(clearTimeout), [])

  useEffect(() => {
    if (yaAbierta) onAbierta()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!abierta) return
    if (!yaAbierta) titulo.current?.focus({ preventScroll: true })
    // En escritorio la portada sigue apenas al cursor.
    const el = escena.current
    const tarjeta = portada.current
    if (!el || !tarjeta || !tienePunteroFino() || prefiereMenosMovimiento()) return
    const mover = (e: PointerEvent) => {
      const r = tarjeta.getBoundingClientRect()
      const x = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / r.width))
      const y = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / r.height))
      tarjeta.style.setProperty('--ty', `${x * 6}deg`)
      tarjeta.style.setProperty('--tx', `${y * -6}deg`)
    }
    const soltar = () => {
      tarjeta.style.setProperty('--tx', '0deg')
      tarjeta.style.setProperty('--ty', '0deg')
    }
    el.addEventListener('pointermove', mover)
    el.addEventListener('pointerleave', soltar)
    return () => {
      el.removeEventListener('pointermove', mover)
      el.removeEventListener('pointerleave', soltar)
    }
  }, [abierta])

  const despues = (fn: () => void, ms: number) => {
    temporizadores.current.push(window.setTimeout(fn, ms))
  }

  const terminar = () => {
    animaciones.current.forEach(a => a.cancel())
    animaciones.current = []
    setFase('abierta')
    onAbierta()
  }

  // Tocar la notificación señala el sello: ahí es donde hay que tocar.
  const senalarSello = () => {
    if (!listo || abriendo || prefiereMenosMovimiento()) return
    sello.current?.animate(
      [{ rotate: '0deg' }, { rotate: '-5deg', offset: 0.25 }, { rotate: '3.5deg', offset: 0.55 }, { rotate: '-1.5deg', offset: 0.8 }, { rotate: '0deg' }],
      { duration: 450, easing: EASE_OUT },
    )
  }

  const romper = () => {
    if (fase !== 'listo') return
    setPresionando(false)
    setFase('abriendo')
    vibrar([10, 40, 16])
    const piezas = [...(escena.current?.querySelectorAll<HTMLElement>('.sobre-pieza') ?? [])]

    if (prefiereMenosMovimiento()) {
      piezas.forEach(p => p.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 450, delay: 150, easing: 'ease', fill: 'forwards' }))
      despues(terminar, 650)
      return
    }

    migas.current.forEach((miga, i) => {
      const angulo = (i / MIGAS) * Math.PI * 2 + 0.4
      const d = 34 + (i % 3) * 16
      miga?.animate(
        [
          { opacity: 1, transform: 'translate(0, 0) rotate(0deg) scale(1)' },
          { opacity: 1, transform: `translate(${Math.cos(angulo) * d}px, ${Math.sin(angulo) * d * 0.6 - 10}px) rotate(${120 + i * 40}deg) scale(.9)`, offset: 0.45 },
          { opacity: 0, transform: `translate(${Math.cos(angulo) * d * 1.2}px, ${Math.sin(angulo) * d * 0.6 + 46}px) rotate(${220 + i * 50}deg) scale(.6)` },
        ],
        { duration: 820, delay: 90, easing: EASE_OUT },
      )
    })

    const alto = portada.current?.offsetHeight ?? 0
    const giro = (extra: string) => [
      { transform: `perspective(1100px) rotateX(0deg) ${extra}` },
      { transform: `perspective(1100px) rotateX(180deg) ${extra}` },
    ]
    const abrir: KeyframeAnimationOptions = { duration: 850, delay: 170, easing: EASE_IN_OUT, fill: 'both' }
    animaciones.current = [
      solapaCara.current?.animate(giro(''), abrir),
      solapaForro.current?.animate(giro('rotateY(180deg)'), abrir),
      // La cámara se aleja para que quepan la solapa abierta y la tarjeta saliendo, y vuelve.
      camara.current?.animate(
        [{ transform: 'scale(1)' }, { transform: 'scale(.74)', offset: 0.42 }, { transform: 'scale(.74)', offset: 0.62 }, { transform: 'scale(1)' }],
        { duration: 2500, delay: 140, easing: EASE_LENTO, fill: 'both' },
      ),
      // La tarjeta sale inclinándose hacia ti y aterriza con un golpe suave.
      portada.current?.animate(
        [
          { transform: 'perspective(1400px) translateY(0) rotateX(0deg) scale(1)' },
          { transform: `perspective(1400px) translateY(${-alto * 0.4}px) rotateX(11deg) scale(1)`, offset: 0.48 },
          { transform: 'perspective(1400px) translateY(0) rotateX(0deg) scale(1.025)', offset: 0.86 },
          { transform: 'perspective(1400px) translateY(0) rotateX(0deg) scale(1)' },
        ],
        { duration: 1850, delay: 940, easing: EASE_LENTO, fill: 'both' },
      ),
    ].filter((a): a is Animation => Boolean(a))

    // El sobre se retira hacia abajo entero y solo se funde al final.
    const baja = alto * 1.25
    piezas.forEach(p =>
      p.animate(
        [
          { translate: '-50% -50%', opacity: 1 },
          { translate: `-50% calc(-50% + ${baja * 0.75}px)`, opacity: 1, offset: 0.7 },
          { translate: `-50% calc(-50% + ${baja}px)`, opacity: 0 },
        ],
        { duration: 900, delay: 1750, easing: EASE_LENTO, fill: 'forwards' },
      ),
    )
    despues(() => vibrar(12), 2650)
    despues(terminar, 2800)
  }

  return (
    <section ref={escena} id="escena" className={clases('escena', listo && 'listo', abriendo && 'abriendo', abierta && 'abierta')}>
      <div ref={camara} className="camara">
        <div className="sobre-pieza sobre-dentro" aria-hidden="true">
          <span className="forro-encaje" />
        </div>
        <div ref={solapaForro} className="sobre-pieza solapa solapa-forro" aria-hidden="true">
          <div className="solapa-forro-papel">
            <span className="forro-encaje" />
          </div>
        </div>

        <article ref={portada} id="portada" className={clases('tarjeta portada', abierta && 'visto')} inert={!abierta}>
          <span className="marco" aria-hidden="true">
            <span className="m-h" />
            <span className="m-v" />
          </span>
          <span className="esquinas" aria-hidden="true" />
          <p className="para">Para ti. Nadie más.</p>
          <svg className="blason" viewBox="0 0 80 80" aria-hidden="true" focusable="false">
            <use href="#blason" />
          </svg>
          <h1 ref={titulo} tabIndex={-1}>
            Hay una fiesta en la Ciudad de México…
          </h1>
          <span className="ornamento" aria-hidden="true" />
          <p id="remate" className={clases('remate palabras', abierta && 'visto')}>
            <Palabras texto="…y esta noche alguien no va a salir viva." />
          </p>
          <span className="brillo" aria-hidden="true" />
        </article>

        <div className="sobre-pieza sobre-bolsillo" aria-hidden="true">
          <div className="bolsillo-papel" />
          <div className="panel-fondo" />
          <svg className="pliegues" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
            <path className="sombra" d="M0 99.2L50 59.2L100 99.2" />
            <path d="M0 99.6L50 59.6L100 99.6" />
          </svg>
        </div>
        <div ref={solapaCara} className="sobre-pieza solapa solapa-cara" aria-hidden="true">
          <div className="solapa-papel" />
          <span className="canto" />
          <svg className="filo" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
            <polyline points="0,0 46.8,54.3 48.4,55.6 50,56 51.6,55.6 53.2,54.3 100,0" />
          </svg>
        </div>

        <div className="sobre-pieza sobre-sello">
          <button
            ref={sello}
            id="sello"
            type="button"
            className={clases('sello', abriendo && 'roto', presionando && 'presionando')}
            aria-label="Romper el sello y abrir la invitación"
            onPointerDown={() => {
              if (fase !== 'listo') return
              // Al presionar, el sello cede y empieza a agrietarse; al soltar, se rompe.
              setPresionando(true)
              vibrar(6)
            }}
            onPointerLeave={() => setPresionando(false)}
            onPointerCancel={() => setPresionando(false)}
            onClick={romper}
          >
            <svg className="sello-entero" viewBox="0 0 240 240" aria-hidden="true" focusable="false">
              <use href="#cera" />
              <g clipPath="url(#cera-clip)">
                <g transform="skewX(-18)">
                  <rect className="destello" x="-110" y="-40" width="64" height="320" fill="url(#destello)" />
                </g>
              </g>
              <g clipPath="url(#cera-clip)">
                <polyline className="grieta-luz" pathLength={100} transform="translate(1 .6)" points={GRIETA} />
                <polyline className="grieta" pathLength={100} points={GRIETA} />
              </g>
            </svg>
            <span className="mitad izq" aria-hidden="true">
              <span className="recorte">
                <svg viewBox="0 0 240 240" focusable="false">
                  <use href="#cera" />
                </svg>
              </span>
            </span>
            <span className="mitad der" aria-hidden="true">
              <span className="recorte">
                <svg viewBox="0 0 240 240" focusable="false">
                  <use href="#cera" />
                </svg>
              </span>
            </span>
          </button>
          {Array.from({ length: MIGAS }, (_, i) => (
            <span
              key={i}
              ref={el => {
                migas.current[i] = el
              }}
              className="miga"
              aria-hidden="true"
            />
          ))}
        </div>
      </div>

      <div id="push" className="push" role="status" onClick={senalarSello}>
        <span className="push-avatar" aria-hidden="true">
          X
        </span>
        <span className="push-texto">
          <span className="push-meta">
            <b>Remitente desconocido</b>
            <span>ahora</span>
          </span>
          <span>Tengo algo para ti. Rompe el sello.</span>
        </span>
      </div>
      <p className="sobre-hint">
        <span>Toca el sello</span>
      </p>
    </section>
  )
}
