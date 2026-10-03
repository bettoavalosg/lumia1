import { useState } from 'react'
import type { SecretoAdmin } from '../servidor/tipos'
import { Seccion, useAdmin } from './comun'

const ETIQUETA = { pendiente: 'Por revisar', aprobado: 'Aprobado', rechazado: 'Rechazado', revelado: 'Ya salió' } as const

export function Secretos() {
  const { a, actuar } = useAdmin()
  const [editando, setEditando] = useState<string | null>(null)
  const pendientes = a.secrets.filter(s => s.status === 'pendiente').length
  const aprobados = a.secrets.filter(s => s.status === 'aprobado').length

  return (
    <Seccion titulo="Secretos" nota="Anónimos: aquí no ves quién escribió cada uno. Solo los aprobados entran al juego; salen uno por cada fallo del grupo.">
      <p className="ad-resumen">
        <b>{pendientes}</b> por revisar · <b>{aprobados}</b> en el juego · {a.secrets.filter(s => s.status === 'revelado').length} ya salieron
      </p>
      {pendientes > 0 && (
        <button type="button" className="secundario" onClick={() => void actuar('admin_approve_all', {}, 'Aprobados.')}>
          Aprobar los {pendientes} pendientes
        </button>
      )}
      <ul className="ad-secretos">
        {a.secrets.map(s => (
          <Tarjeta key={s.id} s={s} editando={editando === s.id} alEditar={() => setEditando(s.id)} alCerrar={() => setEditando(null)} />
        ))}
        {a.secrets.length === 0 && <li className="ad-vacio">Todavía no hay secretos. Llegan con cada respuesta a la invitación.</li>}
      </ul>
    </Seccion>
  )
}

function Tarjeta({ s, editando, alEditar, alCerrar }: { s: SecretoAdmin; editando: boolean; alEditar: () => void; alCerrar: () => void }) {
  const { actuar } = useAdmin()
  const [sobre, setSobre] = useState(s.about)
  const [texto, setTexto] = useState(s.text)
  const fijar = (estado: 'pendiente' | 'aprobado' | 'rechazado') => void actuar('admin_secret', { p_id: s.id, p_status: estado })

  return (
    <li className={`ad-secreto ${s.status}`}>
      <div className="ad-secreto-cab">
        <span className="ad-sello-estado">{ETIQUETA[s.status]}</span>
        <span className="ad-sobre">
          Sobre <em>{s.about}</em>
        </span>
      </div>
      {editando ? (
        <form
          className="ad-editar"
          onSubmit={async ev => {
            ev.preventDefault()
            const r = await actuar('admin_secret', { p_id: s.id, p_about: sobre, p_text: texto }, 'Guardado.')
            if (r) alCerrar()
          }}
        >
          <div className="campo">
            <label htmlFor={`sobre-${s.id}`}>Sobre quién</label>
            <input id={`sobre-${s.id}`} value={sobre} maxLength={40} onChange={ev => setSobre(ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor={`texto-${s.id}`}>El secreto</label>
            <textarea id={`texto-${s.id}`} value={texto} maxLength={280} onChange={ev => setTexto(ev.target.value)} />
          </div>
          <div className="ad-fila-botones">
            <button type="submit" className="secundario" disabled={!sobre.trim() || !texto.trim()}>
              Guardar
            </button>
            <button type="button" className="j-enlace" onClick={alCerrar}>
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <blockquote className="ad-texto">{s.text}</blockquote>
      )}
      {!editando && s.status !== 'revelado' && (
        <div className="ad-fila-botones">
          {s.status !== 'aprobado' && (
            <button type="button" className="secundario" onClick={() => fijar('aprobado')}>
              Aprobar
            </button>
          )}
          {s.status !== 'rechazado' && (
            <button type="button" className="secundario peligro" onClick={() => fijar('rechazado')}>
              Rechazar
            </button>
          )}
          {s.status !== 'pendiente' && (
            <button type="button" className="j-enlace" onClick={() => fijar('pendiente')}>
              Volver a revisar
            </button>
          )}
          <button type="button" className="j-enlace" onClick={alEditar}>
            Editar
          </button>
        </div>
      )}
    </li>
  )
}
