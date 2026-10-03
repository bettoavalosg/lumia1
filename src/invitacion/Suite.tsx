import { useEffect, useRef, useState } from 'react'
import { clases } from '../lib/clases'
import { EASE_OUT, prefiereMenosMovimiento } from '../lib/movimiento'
import { CartaTarot } from './CartaTarot'
import { Marco } from './Marco'
import { Palabras } from './Palabras'
import { Reloj } from './Reloj'
import { useRevelado } from './Revelar'
import { Rsvp } from './Rsvp'
import { useServidor } from '../servidor/Servidor'
import type { Estado } from '../servidor/tipos'

const NEGATIVAS = ['Todavía no.', 'Dije que todavía no.', 'Se voltea el 24 a las 6:00 pm. Ni un minuto antes.', 'Qué ganas de saber, ¿no?']

/** Todo lo que viene después de la portada. `orden` sigue el orden de la página para el revelado. */
export function Suite({ abierta, alEntrar, alCeremonia }: { abierta: boolean; alEntrar?: () => void; alCeremonia?: (enCurso: boolean) => void }) {
  return (
    <div className="suite" id="suite" inert={!abierta}>
      <Narrador orden={0} />
      <Destino orden={1} />
      <Detalles orden={3} />
      <Reglas orden={4} />
      <Rsvp orden={5} alEntrar={alEntrar} alCeremonia={alCeremonia} />
      <Cierre orden={6} />
    </div>
  )
}

function Narrador({ orden }: { orden: number }) {
  const [ref, visto] = useRevelado<HTMLParagraphElement>(orden)
  return (
    <p ref={ref} className={clases('narrador palabras', visto && 'visto')}>
      <Palabras texto="Mariela cumple 29 y sus amigos están convocados. Un departamento, veinte invitados y, entre ustedes, un asesino. Nadie sabe quién. Ni siquiera yo. Por ahora." />
    </p>
  )
}

function Destino({ orden }: { orden: number }) {
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  const [refCarta, cartaVista] = useRevelado<HTMLDivElement>(orden + 1)
  const [aviso, setAviso] = useState({ texto: '', vez: 0 })
  const refAviso = useRef<HTMLParagraphElement>(null)
  const intentos = useRef(0)
  const borrar = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!aviso.vez) return
    const fotogramas = prefiereMenosMovimiento()
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [
          { opacity: 0, transform: 'translateY(4px)' },
          { opacity: 1, transform: 'none' },
        ]
    refAviso.current?.animate(fotogramas, { duration: 180, easing: EASE_OUT })
  }, [aviso.vez])
  useEffect(() => () => clearTimeout(borrar.current), [])

  const rechazar = () => {
    const texto = NEGATIVAS[Math.min(intentos.current++, NEGATIVAS.length - 1)]
    setAviso(a => ({ texto, vez: a.vez + 1 }))
    clearTimeout(borrar.current)
    borrar.current = window.setTimeout(() => setAviso(a => ({ ...a, texto: '' })), 3200)
  }

  return (
    <section ref={ref} className={clases('destino', visto && 'visto')} aria-labelledby="t-carta">
      <h2 id="t-carta" className="palabras">
        <Palabras texto="Tu carta ya está elegida." />
      </h2>
      <div ref={refCarta} className={clases('carta-escena repartir desde-der', cartaVista && 'visto')}>
        <CartaTarot onIntento={rechazar} />
        <span className="carta-sombra" aria-hidden="true" />
      </div>
      <p className="destino-texto">Inocente o asesino. Ni yo sé cuál te tocó.</p>
      <Reloj />
      <p ref={refAviso} className="aviso" id="aviso" aria-live="polite">
        {aviso.texto}
      </p>
    </section>
  )
}

function Detalles({ orden }: { orden: number }) {
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  // La dirección llega del servidor solo después de la fecha que fija el admin; antes, ni siquiera existe en el cliente.
  const direccion = useServidor<Estado>().estado?.event.address ?? null
  return (
    <section ref={ref} className={clases('tarjeta pieza-suite dibujo repartir desde-izq', visto && 'visto')}>
      <Marco />
      <dl className="datos">
        <div className="escalon" style={{ '--e': 0 }}>
          <dt>Cuándo</dt>
          <dd>
            {'Sábado 24 de octubre, 6:00 pm'}
            <small>Llega a tiempo. Sin carta no juegas.</small>
          </dd>
        </div>
        <div className="escalon" style={{ '--e': 1 }}>
          <dt>Dónde</dt>
          {direccion ? (
            <dd>
              {direccion}
              <small>
                Ya no es un secreto.{' '}
                <a className="enlace" href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(direccion)}`} target="_blank" rel="noreferrer">
                  Abrir en Maps
                </a>
              </small>
            </dd>
          ) : (
            <dd>
              Se revela unos días antes.<small>Es un secreto que todavía no voy a contar.</small>
            </dd>
          )}
        </div>
        <div className="escalon" style={{ '--e': 2 }}>
          <dt>Qué ponerte</dt>
          <dd>
            All black. Literal.<small>Negro de pies a cabeza. Si llegas con color, todos lo van a notar.</small>
          </dd>
        </div>
      </dl>
      <span className="brillo" aria-hidden="true" />
    </section>
  )
}

function Reglas({ orden }: { orden: number }) {
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  return (
    <section ref={ref} className={clases('tarjeta pieza-suite reglas dibujo repartir desde-der', visto && 'visto')} aria-labelledby="t-reglas">
      <Marco />
      <h2 id="t-reglas" className="escalon" style={{ '--e': 0 }}>
        Las reglas de la noche
      </h2>
      <span className="ornamento" aria-hidden="true" />
      <ol>
        <li>
          <span>Al llegar, tu celular te da una carta: inocente o asesino. No se la enseñes a nadie.</span>
        </li>
        <li>
          <span>Cada 20 minutos se abre la votación. Todos votan por quien creen que es el asesino.</span>
        </li>
        <li>
          <span>
            Si aciertan, el asesino se toma un shot y se reparten cartas nuevas. Si fallan, quienes votaron mal se toman un shot, sale a la luz un secreto y el
            asesino elige a su siguiente víctima.
          </span>
        </li>
      </ol>
      <span className="brillo" aria-hidden="true" />
    </section>
  )
}

function Cierre({ orden }: { orden: number }) {
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  return (
    <footer ref={ref} className={clases('cierre', visto && 'visto')}>
      <p className="palabras">
        <Palabras texto="Nos vemos el 24, de luto riguroso." />
      </p>
      <span className="firma">XOXO</span>
    </footer>
  )
}
