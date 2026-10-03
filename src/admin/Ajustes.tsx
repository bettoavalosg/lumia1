import { useMemo, useState, type FormEvent } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { sesionAdmin } from '../servidor/identidad'
import { aIso, aLocal, Confirmar, Seccion, useAdmin } from './comun'

interface Valores {
  starts_at: string
  address: string
  address_reveal_at: string
  round_min: string
  vote_min: string
  tiebreak_seconds: string
  kill_seconds: string
  pause_seconds: string
  killers_threshold: string
  opening_kill: boolean
  door_code: string
  rehearsal: boolean
}

const minutos = (segundos: number) => String(Math.round((segundos / 60) * 100) / 100)

export function Ajustes() {
  const { a, actuar } = useAdmin()
  const avisar = useAvisos()
  const ev = a.event
  const inicial = useMemo<Valores>(
    () => ({
      starts_at: aLocal(ev.starts_at),
      address: ev.address ?? '',
      address_reveal_at: aLocal(ev.address_reveal_at),
      round_min: minutos(ev.durations.round),
      vote_min: minutos(ev.durations.vote),
      tiebreak_seconds: String(ev.durations.tiebreak),
      kill_seconds: String(ev.durations.kill),
      pause_seconds: String(ev.durations.pause),
      killers_threshold: String(ev.killers_threshold),
      opening_kill: ev.opening_kill,
      door_code: ev.door_code ?? '',
      rehearsal: ev.rehearsal,
    }),
    // Solo se vuelve a tomar del servidor tras guardar (cambia la versión).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [a.version],
  )
  const [v, setV] = useState<Valores>(inicial)
  const [base, setBase] = useState(inicial)
  const [confirmarEnsayo, setConfirmarEnsayo] = useState(false)
  if (base !== inicial && JSON.stringify(base) !== JSON.stringify(inicial)) {
    // El servidor cambió por fuera (otro admin, o un guardado): se sincroniza lo que no se está editando.
    setBase(inicial)
    setV(inicial)
  }
  const cambia = <K extends keyof Valores>(k: K, valor: Valores[K]) => setV(x => ({ ...x, [k]: valor }))
  const sucio = JSON.stringify(v) !== JSON.stringify(base)

  const guardar = async (ev2?: FormEvent) => {
    ev2?.preventDefault()
    const c: Record<string, unknown> = {}
    if (v.starts_at !== base.starts_at) c.starts_at = aIso(v.starts_at)
    if (v.address !== base.address) c.address = v.address
    if (v.address_reveal_at !== base.address_reveal_at) c.address_reveal_at = aIso(v.address_reveal_at)
    if (v.round_min !== base.round_min) c.round_seconds = Math.round(Number(v.round_min) * 60)
    if (v.vote_min !== base.vote_min) c.vote_seconds = Math.round(Number(v.vote_min) * 60)
    if (v.tiebreak_seconds !== base.tiebreak_seconds) c.tiebreak_seconds = Number(v.tiebreak_seconds)
    if (v.kill_seconds !== base.kill_seconds) c.kill_seconds = Number(v.kill_seconds)
    if (v.pause_seconds !== base.pause_seconds) c.pause_seconds = Number(v.pause_seconds)
    if (v.killers_threshold !== base.killers_threshold) c.killers_threshold = Number(v.killers_threshold)
    if (v.opening_kill !== base.opening_kill) c.opening_kill = v.opening_kill
    if (v.door_code !== base.door_code) c.door_code = v.door_code
    if (v.rehearsal !== base.rehearsal) c.rehearsal = v.rehearsal
    if (Object.keys(c).length === 0) return
    const r = await actuar('admin_config', { p_changes: c }, 'Guardado.')
    if (r) setBase(v)
  }

  const zona = Intl.DateTimeFormat().resolvedOptions().timeZone

  return (
    <form onSubmit={guardar} className="ad-ajustes">
      <Seccion titulo="La fiesta" nota={`Las horas son las de este dispositivo (${zona}).`}>
        <div className="campo">
          <label htmlFor="a-inicio">Empieza</label>
          <input id="a-inicio" type="datetime-local" value={v.starts_at} onChange={ev => cambia('starts_at', ev.target.value)} />
        </div>
        <div className="campo">
          <label htmlFor="a-direccion">Dirección</label>
          <textarea id="a-direccion" value={v.address} maxLength={300} onChange={ev => cambia('address', ev.target.value)} />
          <p className="hint">Nunca llega a los teléfonos antes de la hora de revelado: el servidor no la manda.</p>
        </div>
        <div className="campo">
          <label htmlFor="a-revela">Revelar la dirección el</label>
          <input id="a-revela" type="datetime-local" value={v.address_reveal_at} onChange={ev => cambia('address_reveal_at', ev.target.value)} />
          <div className="ad-fila-botones">
            <button type="button" className="j-enlace" onClick={() => cambia('address_reveal_at', aLocal(new Date(Date.now() - 60_000).toISOString()))}>
              Revelar ya
            </button>
            <button type="button" className="j-enlace" onClick={() => cambia('address_reveal_at', '')}>
              No revelar todavía
            </button>
          </div>
        </div>
      </Seccion>

      <Seccion titulo="Tiempos" nota="Cada cuánto se vota y cuánto dura cada momento.">
        <div className="ad-rejilla">
          <div className="campo">
            <label htmlFor="a-ronda">Ronda (min)</label>
            <input id="a-ronda" inputMode="decimal" value={v.round_min} onChange={ev => cambia('round_min', ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="a-voto">Votación (min)</label>
            <input id="a-voto" inputMode="decimal" value={v.vote_min} onChange={ev => cambia('vote_min', ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="a-desempate">Desempate (s)</label>
            <input id="a-desempate" inputMode="numeric" value={v.tiebreak_seconds} onChange={ev => cambia('tiebreak_seconds', ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="a-golpe">Elige víctima (s)</label>
            <input id="a-golpe" inputMode="numeric" value={v.kill_seconds} onChange={ev => cambia('kill_seconds', ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="a-pausa">Entre partidas (s)</label>
            <input id="a-pausa" inputMode="numeric" value={v.pause_seconds} onChange={ev => cambia('pause_seconds', ev.target.value)} />
          </div>
        </div>
      </Seccion>

      <Seccion titulo="Reglas y puerta">
        <div className="campo">
          <label htmlFor="a-umbral">Dos asesinos si hay más de… presentes</label>
          <input id="a-umbral" inputMode="numeric" value={v.killers_threshold} onChange={ev => cambia('killers_threshold', ev.target.value)} />
        </div>
        <label className="ad-check">
          <input type="checkbox" checked={v.opening_kill} onChange={ev => cambia('opening_kill', ev.target.checked)} />
          <span>
            <b>Muerte de apertura</b>
            <small>Al repartir, el asesino elige a una primera víctima para que la primera votación no sea a ciegas.</small>
          </span>
        </label>
        <div className="campo">
          <label htmlFor="a-codigo">Código de la puerta</label>
          <input id="a-codigo" value={v.door_code} maxLength={12} autoCapitalize="characters" spellCheck={false} onChange={ev => cambia('door_code', ev.target.value.toUpperCase())} />
          <p className="hint">Si lo pones, para marcar “Estoy aquí” hay que escribirlo. Sale en la tele.</p>
          <div className="ad-fila-botones">
            <button type="button" className="j-enlace" onClick={() => cambia('door_code', Math.random().toString(36).slice(2, 6).toUpperCase())}>
              Generar uno
            </button>
            <button type="button" className="j-enlace" onClick={() => cambia('door_code', '')}>
              Sin código
            </button>
          </div>
        </div>
      </Seccion>

      <Seccion titulo="Ensayo" nota="Un modo para probar la noche completa antes de la fiesta: hay bots y el reloj se puede adelantar. Apágalo para la noche real.">
        <label className="ad-check">
          <input
            type="checkbox"
            checked={v.rehearsal}
            onChange={ev => {
              if (!ev.target.checked && base.rehearsal) setConfirmarEnsayo(true)
              else cambia('rehearsal', ev.target.checked)
            }}
          />
          <span>
            <b>Modo ensayo</b>
            <small>{v.rehearsal ? 'Encendido. Aparece la pestaña Ensayo.' : 'Apagado.'}</small>
          </span>
        </label>
      </Seccion>

      <div className="ad-guardar">
        <button type="submit" className="primario" id="ad-guardar" disabled={!sucio}>
          {sucio ? 'Guardar cambios' : 'Todo guardado'}
        </button>
      </div>

      <Pin avisar={avisar} />

      <Confirmar
        abierta={confirmarEnsayo}
        titulo="¿Apagar el ensayo?"
        texto="Se van los bots y el reloj vuelve a la hora real. Los invitados de verdad se quedan."
        boton="Apagar el ensayo"
        peligro
        alConfirmar={() => cambia('rehearsal', false)}
        alCerrar={() => setConfirmarEnsayo(false)}
      />
    </form>
  )
}

function Pin({ avisar }: { avisar: (t: string, tipo?: 'info' | 'ok' | 'error') => void }) {
  const { actuar } = useAdmin()
  const [nuevo, setNuevo] = useState('')
  const [otra, setOtra] = useState('')
  const invalido = nuevo.length < 6 || nuevo !== otra

  const cambiar = async () => {
    const r = await actuar('admin_set_pin', { p_new: nuevo })
    if (r) {
      avisar('PIN cambiado. Vuelve a entrar.', 'ok')
      sesionAdmin.borrar()
      location.reload()
    }
  }

  return (
    <Seccion titulo="PIN de admin" nota="Al menos 6 caracteres. Se verifica en el servidor y nunca se guarda en claro.">
      <div className="ad-rejilla">
        <div className="campo">
          <label htmlFor="pin-nuevo">Nuevo PIN</label>
          <input id="pin-nuevo" type="password" autoComplete="new-password" value={nuevo} onChange={ev => setNuevo(ev.target.value)} />
        </div>
        <div className="campo">
          <label htmlFor="pin-otra">Repítelo</label>
          <input id="pin-otra" type="password" autoComplete="new-password" value={otra} onChange={ev => setOtra(ev.target.value)} />
        </div>
      </div>
      <button type="button" className="secundario" disabled={invalido} onClick={() => void cambiar()}>
        Cambiar PIN
      </button>
    </Seccion>
  )
}
