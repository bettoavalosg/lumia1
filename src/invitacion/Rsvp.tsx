import { useEffect, useRef, useState, type FormEvent } from 'react'
import { clases } from '../lib/clases'
import { descargarIcs } from '../lib/ics'
import { EASE_OUT, prefiereMenosMovimiento, vibrar } from '../lib/movimiento'
import { Marco } from './Marco'
import { Palabras } from './Palabras'
import { useRevelado } from './Revelar'

type Campo = 'nombre' | 'quien' | 'secreto'
type Valores = Record<Campo, string>
const CAMPOS: Campo[] = ['nombre', 'quien', 'secreto']
const LIMITE = 280

const normalizar = (s: string) => s.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')

function validar(v: Valores): Partial<Record<Campo, string>> {
  const errores: Partial<Record<Campo, string>> = {}
  if (!v.nombre) errores.nombre = 'Escribe tu nombre.'
  if (!v.quien) errores.quien = 'Escribe de quién es el secreto.'
  else if (v.nombre && normalizar(v.quien) === normalizar(v.nombre)) errores.quien = 'Tiene que ser de otro invitado.'
  if (!v.secreto) errores.secreto = 'Escribe el secreto.'
  return errores
}

/** La tarjeta de respuesta: nombre y un secreto de otro invitado. En Fase 1 no se envía nada. */
export function Rsvp({ orden, secretosGuardados = 0 }: { orden: number; secretosGuardados?: number }) {
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  const [valores, setValores] = useState<Valores>({ nombre: '', quien: '', secreto: '' })
  const [errores, setErrores] = useState<Partial<Record<Campo, string>>>({})
  const [sellando, setSellando] = useState(false)
  const [tachar, setTachar] = useState(false)
  const [estampado, setEstampado] = useState(false)
  const [hecho, setHecho] = useState(false)
  const [sellado, setSellado] = useState({ nombre: '', palabras: [] as string[] })
  const campos = {
    nombre: useRef<HTMLInputElement>(null),
    quien: useRef<HTMLInputElement>(null),
    secreto: useRef<HTMLTextAreaElement>(null),
  }
  const aceptado = useRef<HTMLDivElement>(null)
  const temporizadores = useRef<number[]>([])

  useEffect(() => () => temporizadores.current.forEach(clearTimeout), [])
  useEffect(() => {
    if (hecho) aceptado.current?.focus({ preventScroll: true })
  }, [hecho])

  const cambiar = (campo: Campo) => (e: { target: { value: string } }) => setValores(v => ({ ...v, [campo]: e.target.value }))

  const enviar = (e: FormEvent) => {
    e.preventDefault()
    const v: Valores = { nombre: valores.nombre.trim(), quien: valores.quien.trim(), secreto: valores.secreto.trim() }
    const nuevos = validar(v)
    setErrores(nuevos)
    const primero = CAMPOS.find(c => nuevos[c])
    if (primero) {
      const el = campos[primero].current
      // El campo que falta tiembla una vez, como la carta que no se deja voltear.
      if (!prefiereMenosMovimiento()) {
        el?.animate([{ translate: '0' }, { translate: '-6px' }, { translate: '5px' }, { translate: '-3px' }, { translate: '0' }], { duration: 320, easing: 'ease-out' })
      }
      vibrar([8, 30, 8])
      el?.focus()
      return
    }

    // TODO(Fase 2): insert en players { name } y en secrets { author_id, about_name, body, status: 'pendiente' }.
    // La animación de sellado debe cubrir la latencia de la red; si falla, se "des-sella" con el error.
    const palabras = v.secreto.split(/\s+/)
    const menos = prefiereMenosMovimiento()
    setSellado({ nombre: v.nombre, palabras })
    setSellando(true)
    requestAnimationFrame(() => requestAnimationFrame(() => setTachar(true)))
    const tachado = menos ? 0 : 300 + Math.min(palabras.length, 30) * 35
    temporizadores.current.push(
      window.setTimeout(() => {
        setEstampado(true)
        if (!menos) ref.current?.animate([{ scale: '1' }, { scale: '.985', offset: 0.35 }, { scale: '1' }], { duration: 320, easing: EASE_OUT })
        vibrar(18)
      }, menos ? 150 : tachado + 140),
      window.setTimeout(() => setHecho(true), menos ? 450 : tachado + 140 + 560),
    )
  }

  const atributos = (campo: Campo, extra: string) => ({
    id: campo === 'quien' ? 'sobre-quien' : campo,
    value: valores[campo],
    onChange: cambiar(campo),
    'aria-invalid': errores[campo] ? true : undefined,
    'aria-describedby': extra,
  })

  let escalon = 0
  const siguiente = () => ({ '--e': escalon++ })

  return (
    <section ref={ref} id="rsvp" className={clases('tarjeta pieza-suite rsvp dibujo subir', visto && 'visto')} aria-labelledby="t-rsvp">
      <Marco />
      <p className="rsvp-pre escalon" style={siguiente()}>
        Cada invitado deja un secreto de alguien más.
      </p>
      <h2 className="sentencia palabras" id="t-rsvp">
        <Palabras texto="Alguien va a escribir uno sobre ti." />
      </h2>
      <p className="rsvp-post escalon" style={siguiente()}>
        La única forma de defenderte es estar ahí. Para aceptar, deja tu nombre y un secreto de otro invitado.
      </p>
      {secretosGuardados > 0 && (
        <p className="conteo" id="conteo">
          {secretosGuardados} {secretosGuardados === 1 ? 'secreto guardado' : 'secretos guardados'} hasta ahora.
        </p>
      )}
      <span className="ornamento" aria-hidden="true" />

      <form id="form" noValidate onSubmit={enviar} hidden={sellando}>
        <div className="campo escalon" style={siguiente()}>
          <label htmlFor="nombre">Tu nombre</label>
          <input ref={campos.nombre} name="nombre" autoComplete="name" autoCapitalize="words" enterKeyHint="next" {...atributos('nombre', 'e-nombre')} />
          <p className="error" id="e-nombre" aria-live="polite">
            {errores.nombre}
          </p>
        </div>
        <div className="campo escalon" style={siguiente()}>
          <label htmlFor="sobre-quien">¿De quién es el secreto?</label>
          <p className="hint" id="h-quien">
            Otro invitado. El tuyo no cuenta.
          </p>
          <input ref={campos.quien} name="sobre_quien" autoComplete="off" autoCapitalize="words" enterKeyHint="next" {...atributos('quien', 'h-quien e-quien')} />
          <p className="error" id="e-quien" aria-live="polite">
            {errores.quien}
          </p>
        </div>
        <div className="campo escalon" style={siguiente()}>
          <label htmlFor="secreto">El secreto</label>
          <p className="hint" id="h-secreto">
            Anónimo. Solo sale a la luz si el grupo falla, y se revisa antes de entrar al juego. Que dé risa, no que termine amistades.
          </p>
          <textarea ref={campos.secreto} name="secreto" maxLength={LIMITE} {...atributos('secreto', 'h-secreto e-secreto')} />
          <span className="contador" id="contador" aria-hidden="true">
            {valores.secreto.length} / {LIMITE}
          </span>
          <p className="error" id="e-secreto" aria-live="polite">
            {errores.secreto}
          </p>
        </div>
        <button type="submit" className="primario escalon" style={siguiente()}>
          Acepto
        </button>
      </form>

      <div id="sellado" className={clases('sellado', tachar && 'tachar', estampado && 'estampado', hecho && 'hecho')} hidden={!sellando} aria-hidden="true">
        <p className="sellado-t">Sellando tu secreto</p>
        <div className="sellado-hoja">
          <p className="sellado-txt" id="sellado-txt">
            {sellado.palabras.map((palabra, i) => (
              <span key={i} style={{ '--i': Math.min(i, 30) }}>
                {palabra}
              </span>
            ))}
          </p>
          <svg className="sellado-sello" viewBox="0 0 240 240" focusable="false">
            <use href="#cera" />
          </svg>
        </div>
      </div>

      <div ref={aceptado} id="aceptado" className="aceptado" hidden={!hecho} tabIndex={-1}>
        <h3>
          Aceptaste, <span id="a-nombre">{sellado.nombre}</span>.
        </h3>
        <p>Tu secreto quedó sellado. Nadie va a saber que fuiste tú.</p>
        <button type="button" className="secundario" id="calendario" onClick={descargarIcs}>
          Agregar al calendario
        </button>
      </div>
      <span className="brillo" aria-hidden="true" />
    </section>
  )
}
