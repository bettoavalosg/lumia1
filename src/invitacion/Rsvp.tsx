import { useEffect, useRef, useState, type FormEvent } from 'react'
import { clases } from '../lib/clases'
import { guardarLlave, llaveGuardada } from '../lib/almacen'
import { descargarIcs } from '../lib/ics'
import { EASE_OUT, prefiereMenosMovimiento, vibrar } from '../lib/movimiento'
import { esErrorDeRed, esErrorJuego, mensajeDe } from '../servidor/errores'
import { guardarToken, nuevoToken, olvidarToken, tokenDispositivo } from '../servidor/identidad'
import { useServidor } from '../servidor/Servidor'
import type { Estado } from '../servidor/tipos'
import { Marco } from './Marco'
import { Palabras } from './Palabras'
import { useRevelado } from './Revelar'

type Campo = 'nombre' | 'quien' | 'secreto'
type Valores = Record<Campo, string>
const CAMPOS: Campo[] = ['nombre', 'quien', 'secreto']
const LIMITE = 280

// Qué campo señala cada error del servidor.
const CAMPO_DEL_ERROR: Record<string, Campo> = {
  nombre_vacio: 'nombre',
  nombre_largo: 'nombre',
  nombre_repetido: 'nombre',
  sobre_vacio: 'quien',
  sobre_largo: 'quien',
  secreto_propio: 'quien',
  secreto_vacio: 'secreto',
  secreto_largo: 'secreto',
}

const normalizar = (s: string) => s.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
const esperar = (ms: number) => new Promise<void>(r => setTimeout(r, ms))

function validar(v: Valores): Partial<Record<Campo, string>> {
  const errores: Partial<Record<Campo, string>> = {}
  if (!v.nombre) errores.nombre = 'Escribe tu nombre.'
  if (!v.quien) errores.quien = 'Escribe de quién es el secreto.'
  else if (v.nombre && normalizar(v.quien) === normalizar(v.nombre)) errores.quien = 'Tiene que ser de otro invitado.'
  if (!v.secreto) errores.secreto = 'Escribe el secreto.'
  return errores
}

interface Props {
  orden: number
  /** Para quien ya está en la noche (puerta abierta): cierra la invitación y pasa al juego. */
  alEntrar?: () => void
  /** Avisa mientras el secreto se está sellando, para que la app no cambie de pantalla a media ceremonia. */
  alCeremonia?: (enCurso: boolean) => void
}

/** La tarjeta de respuesta: nombre y el secreto de otro invitado. El secreto se sella mientras viaja al servidor. */
export function Rsvp({ orden, alEntrar, alCeremonia }: Props) {
  const { estado, backend, refrescar } = useServidor<Estado>()
  const e = estado as Estado
  const me = e.me
  const [ref, visto] = useRevelado<HTMLElement>(orden)
  const [valores, setValores] = useState<Valores>({ nombre: '', quien: '', secreto: '' })
  const [errores, setErrores] = useState<Partial<Record<Campo, string>>>({})
  const [errorGeneral, setErrorGeneral] = useState('')
  const [sellando, setSellando] = useState(false)
  const [tachar, setTachar] = useState(false)
  const [estampado, setEstampado] = useState(false)
  const [hecho, setHecho] = useState(Boolean(me))
  const [sellado, setSellado] = useState({ nombre: me?.name ?? '', palabras: [] as string[] })
  const [llave, setLlave] = useState(llaveGuardada())
  const [recuperando, setRecuperando] = useState(false)
  const [recuperar, setRecuperar] = useState({ nombre: '', llave: '', error: '', enCurso: false })
  const [copiada, setCopiada] = useState(false)
  const campos = {
    nombre: useRef<HTMLInputElement>(null),
    quien: useRef<HTMLInputElement>(null),
    secreto: useRef<HTMLTextAreaElement>(null),
  }
  const aceptado = useRef<HTMLDivElement>(null)
  const vivo = useRef(true)

  useEffect(() => {
    vivo.current = true
    return () => {
      vivo.current = false
    }
  }, [])
  const cambiar = (campo: Campo) => (ev: { target: { value: string } }) => setValores(v => ({ ...v, [campo]: ev.target.value }))

  const sacudir = (campo: Campo) => {
    const el = campos[campo].current
    if (!prefiereMenosMovimiento()) {
      el?.animate([{ translate: '0' }, { translate: '-6px' }, { translate: '5px' }, { translate: '-3px' }, { translate: '0' }], { duration: 320, easing: 'ease-out' })
    }
    vibrar([8, 30, 8])
    el?.focus()
  }

  // El servidor rechazó la respuesta (o no hubo red): el sello se deshace y el error queda donde corresponde.
  const deshacer = (error: unknown, tokenNuevo: boolean) => {
    if (!vivo.current) return
    setSellando(false)
    setTachar(false)
    setEstampado(false)
    alCeremonia?.(false)
    if (esErrorJuego(error) && !esErrorDeRed(error)) {
      if (tokenNuevo) olvidarToken()
      const campo = CAMPO_DEL_ERROR[error.codigo]
      if (campo) {
        setErrores({ [campo]: error.message })
        requestAnimationFrame(() => sacudir(campo))
        return
      }
    }
    setErrorGeneral(esErrorDeRed(error) ? 'No pudimos enviar tu respuesta. Revisa tu conexión y vuelve a intentarlo.' : mensajeDe(error))
    vibrar([8, 30, 8])
  }

  const enviar = async (ev: FormEvent) => {
    ev.preventDefault()
    setErrorGeneral('')
    const v: Valores = { nombre: valores.nombre.trim(), quien: valores.quien.trim(), secreto: valores.secreto.trim() }
    const nuevos = validar(v)
    setErrores(nuevos)
    const primero = CAMPOS.find(c => nuevos[c])
    if (primero) {
      // El campo que falta tiembla una vez, como la carta que no se deja voltear.
      sacudir(primero)
      return
    }

    // El sello cubre la latencia: el secreto se tacha mientras viaja, y se estampa cuando el servidor contesta.
    const palabras = v.secreto.split(/\s+/)
    const menos = prefiereMenosMovimiento()
    setSellado({ nombre: v.nombre, palabras })
    setSellando(true)
    alCeremonia?.(true)
    requestAnimationFrame(() => requestAnimationFrame(() => setTachar(true)))
    const tachado = menos ? 0 : 300 + Math.min(palabras.length, 30) * 35

    // El token se guarda antes de enviar: si la respuesta se pierde, reintentar reconoce a este mismo dispositivo.
    const previo = tokenDispositivo()
    const token = previo ?? nuevoToken()
    if (!previo) guardarToken(token)
    const envio = backend.rpc<{ recovery_key?: string }>('rsvp', { p_token: token, p_name: v.nombre, p_about: v.quien, p_text: v.secreto })
    const [resultado] = await Promise.allSettled([envio, esperar(menos ? 150 : tachado + 140)])
    if (!vivo.current) return
    if (resultado.status === 'rejected') {
      deshacer(resultado.reason, !previo)
      return
    }
    const clave = resultado.value.recovery_key
    if (clave) {
      guardarLlave(clave)
      setLlave(clave)
    }
    setEstampado(true)
    if (!menos) ref.current?.animate([{ scale: '1' }, { scale: '.985', offset: 0.35 }, { scale: '1' }], { duration: 320, easing: EASE_OUT })
    vibrar(18)
    await esperar(menos ? 300 : 560)
    if (!vivo.current) return
    setHecho(true)
    void refrescar()
  }

  useEffect(() => {
    if (hecho) aceptado.current?.focus({ preventScroll: true })
  }, [hecho])

  // -- entrar con la llave (otro teléfono, otro navegador, la app instalada) --------------------------
  const entrarConLlave = async (nombre: string, clave: string) => {
    setRecuperar(r => ({ ...r, error: '', enCurso: true }))
    const token = nuevoToken()
    try {
      const r = await backend.rpc<{ ok: boolean; message?: string; player?: { name: string } }>('recover', { p_name: nombre, p_key: clave, p_token: token })
      if (!r.ok) {
        setRecuperar(x => ({ ...x, error: r.message ?? 'Ese nombre o esa llave no coinciden.', enCurso: false }))
        vibrar([8, 30, 8])
        return
      }
      guardarToken(token)
      guardarLlave(clave.toUpperCase().replace(/[^A-Z0-9]/g, '').replace(/^(.{4})(.{4})$/, '$1-$2'))
      setLlave(llaveGuardada())
      setSellado(s => ({ ...s, nombre: r.player?.name ?? nombre }))
      setHecho(true)
      setRecuperando(false)
      await refrescar()
    } catch (error) {
      setRecuperar(x => ({ ...x, error: mensajeDe(error), enCurso: false }))
    }
    setRecuperar(x => ({ ...x, enCurso: false }))
  }

  // Un enlace del admin (?nombre=…&llave=…) entra solo.
  useEffect(() => {
    if (me) return
    const q = new URLSearchParams(location.search)
    const nombre = q.get('nombre')
    const clave = q.get('llave')
    if (!nombre || !clave) return
    history.replaceState(null, '', location.pathname)
    setRecuperar(r => ({ ...r, nombre, llave: clave }))
    void entrarConLlave(nombre, clave)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const copiarLlave = async () => {
    if (!llave) return
    try {
      await navigator.clipboard.writeText(llave)
      setCopiada(true)
      setTimeout(() => setCopiada(false), 2200)
    } catch {
      // el usuario puede seleccionarla a mano
    }
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
  const nombreAceptado = me?.name ?? sellado.nombre
  const enNoche = e.event.phase === 'lobby' || e.event.phase === 'jugando'
  const estadoSecreto = me?.secret?.status
  const rechazado = estadoSecreto === 'rechazado'
  const guardados = e.event.rsvp_count

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
      {guardados > 0 && (
        <p className="conteo" id="conteo">
          {guardados} {guardados === 1 ? 'secreto guardado' : 'secretos guardados'} hasta ahora.
        </p>
      )}
      <span className="ornamento" aria-hidden="true" />

      <form id="form" noValidate onSubmit={enviar} hidden={sellando || hecho}>
        <div className="campo escalon" style={siguiente()}>
          <label htmlFor="nombre">Tu nombre</label>
          <input ref={campos.nombre} name="nombre" autoComplete="name" autoCapitalize="words" enterKeyHint="next" maxLength={40} {...atributos('nombre', 'e-nombre')} />
          <p className="error" id="e-nombre" aria-live="polite">
            {errores.nombre}
          </p>
        </div>
        <div className="campo escalon" style={siguiente()}>
          <label htmlFor="sobre-quien">¿De quién es el secreto?</label>
          <p className="hint" id="h-quien">
            Otro invitado. El tuyo no cuenta.
          </p>
          <input ref={campos.quien} name="sobre_quien" autoComplete="off" autoCapitalize="words" enterKeyHint="next" maxLength={40} {...atributos('quien', 'h-quien e-quien')} />
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
        <p className="error error-general" id="e-general" role="alert" data-extra>
          {errorGeneral}
        </p>
        <button type="submit" className="primario escalon" style={siguiente()}>
          Acepto
        </button>
        {!hecho && (
          <div className="recuperar" data-extra>
            {!recuperando ? (
              <button type="button" className="enlace" onClick={() => setRecuperando(true)}>
                ¿Ya respondiste desde otro teléfono? Entra con tu llave.
              </button>
            ) : (
              <div className="recuperar-campos">
                <div className="campo">
                  <label htmlFor="rec-nombre">Tu nombre</label>
                  <input id="rec-nombre" autoComplete="name" value={recuperar.nombre} maxLength={40} onChange={ev => setRecuperar(r => ({ ...r, nombre: ev.target.value }))} />
                </div>
                <div className="campo">
                  <label htmlFor="rec-llave">Tu llave</label>
                  <input id="rec-llave" autoComplete="off" autoCapitalize="characters" spellCheck={false} placeholder="ABCD-EFGH" maxLength={12} value={recuperar.llave} onChange={ev => setRecuperar(r => ({ ...r, llave: ev.target.value }))} />
                </div>
                <p className="error" role="alert">
                  {recuperar.error}
                </p>
                <button
                  type="button"
                  className="secundario"
                  disabled={recuperar.enCurso || !recuperar.nombre.trim() || !recuperar.llave.trim()}
                  onClick={() => void entrarConLlave(recuperar.nombre, recuperar.llave)}
                >
                  {recuperar.enCurso ? 'Entrando…' : 'Entrar'}
                </button>
              </div>
            )}
          </div>
        )}
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
          Aceptaste, <span id="a-nombre">{nombreAceptado}</span>.
        </h3>
        <p>Tu secreto quedó sellado. Nadie va a saber que fuiste tú.</p>
        <button type="button" className="secundario" id="calendario" onClick={() => descargarIcs(e.event.address)}>
          Agregar al calendario
        </button>
        {estadoSecreto && !rechazado && (
          <p className="secreto-estado" data-extra>
            {estadoSecreto === 'pendiente' ? 'Tu secreto está en revisión.' : 'Tu secreto ya está en el juego.'}
          </p>
        )}
        {rechazado && me && <Reemplazo />}
        {llave && (
          <div className="llave" data-extra>
            <p className="llave-t">Tu llave</p>
            <p className="llave-c" aria-label={`Tu llave es ${llave.split('').join(' ')}`}>
              {llave}
            </p>
            <p className="llave-h">Guárdala. Si abres esto desde otro teléfono o navegador, con ella recuperas tu lugar.</p>
            <button type="button" className="enlace" onClick={() => void copiarLlave()}>
              {copiada ? 'Copiada' : 'Copiar llave'}
            </button>
          </div>
        )}
        {enNoche && alEntrar && (
          <button type="button" className="primario" onClick={alEntrar} data-extra>
            Entrar a la noche
          </button>
        )}
      </div>
      <span className="brillo" aria-hidden="true" />
    </section>
  )
}

/** Si el admin rechaza el secreto, su autor escribe otro sin perder su lugar. */
function Reemplazo() {
  const { backend, refrescar } = useServidor<Estado>()
  const [v, setV] = useState({ quien: '', secreto: '' })
  const [error, setError] = useState('')
  const [enCurso, setEnCurso] = useState(false)
  const enviar = async (ev: FormEvent) => {
    ev.preventDefault()
    setError('')
    setEnCurso(true)
    try {
      await backend.rpc('replace_secret', { p_token: tokenDispositivo(), p_about: v.quien, p_text: v.secreto })
      await refrescar()
    } catch (e) {
      setError(mensajeDe(e))
    }
    setEnCurso(false)
  }
  return (
    <form className="reemplazo" onSubmit={enviar} data-extra>
      <p className="reemplazo-t">Tu secreto no pasó la revisión. Escribe otro.</p>
      <div className="campo">
        <label htmlFor="rem-quien">¿De quién es?</label>
        <input id="rem-quien" maxLength={40} value={v.quien} onChange={ev => setV(x => ({ ...x, quien: ev.target.value }))} />
      </div>
      <div className="campo">
        <label htmlFor="rem-secreto">El secreto</label>
        <textarea id="rem-secreto" maxLength={LIMITE} value={v.secreto} onChange={ev => setV(x => ({ ...x, secreto: ev.target.value }))} />
      </div>
      <p className="error" role="alert">
        {error}
      </p>
      <button type="submit" className="secundario" disabled={enCurso || !v.quien.trim() || !v.secreto.trim()}>
        {enCurso ? 'Enviando…' : 'Enviar otro'}
      </button>
    </form>
  )
}
