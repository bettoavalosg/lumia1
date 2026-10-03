import { useState } from 'react'
import { useAvisos } from '../compartido/Avisos'
import { enlaceSms, esDireccionLocal, mensajeInvitacion, telefonoE164 } from '../lib/invitacionSms'
import { copiar, Seccion } from './comun'

/**
 * Mandar la invitación desde tu propio teléfono: se abre Mensajes con el texto y el enlace listos, y tú eliges a quién (o escribes su
 * teléfono aquí y se abre su chat). Sale de un número que conocen, sin cuentas ni costo. Nada de lo que escribes se guarda ni sale del
 * dispositivo: solo arma el enlace `sms:`.
 */
export function MandarInvitacion() {
  const avisar = useAvisos()
  const [nombre, setNombre] = useState('')
  const [telefono, setTelefono] = useState('')
  const enlace = `${location.origin}/`
  const e164 = telefono.trim() ? telefonoE164(telefono) : null
  const telefonoMalo = telefono.trim() !== '' && !e164
  const cuerpo = mensajeInvitacion(nombre, enlace)
  const puedeCompartir = typeof navigator.share === 'function'

  const compartir = async () => {
    try {
      await navigator.share({ text: cuerpo })
    } catch (e) {
      // Cerrar el menú sin elegir nada no es un error.
      if (!(e instanceof DOMException && e.name === 'AbortError')) avisar('No pude abrir el menú de compartir. Copia el mensaje y pégalo donde quieras.', 'error')
    }
  }

  return (
    <Seccion
      titulo="Mandar la invitación"
      nota="Se abre tu app de mensajes con el texto y el enlace listos. Sale de tu número, así que te reconocen, y ahí puedes cambiar lo que quieras antes de mandarlo."
    >
      <div className="ad-invitar">
        <div className="ad-invitar-campos">
          <div className="campo">
            <label htmlFor="inv-nombre">Para quién (opcional)</label>
            <input id="inv-nombre" value={nombre} maxLength={40} autoComplete="off" onChange={ev => setNombre(ev.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="inv-telefono">Su teléfono (opcional)</label>
            <input
              id="inv-telefono"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              value={telefono}
              aria-invalid={telefonoMalo || undefined}
              aria-describedby="inv-ayuda"
              onChange={ev => setTelefono(ev.target.value)}
            />
          </div>
        </div>
        <p id="inv-ayuda" className={`ad-ayuda${telefonoMalo ? ' error' : ''}`} aria-live="polite">
          {telefonoMalo
            ? 'Ese teléfono no parece válido. Escríbelo con sus 10 dígitos, o déjalo vacío y eliges a quién en Mensajes.'
            : 'Con teléfono se abre el chat de esa persona; sin él, eliges a quién en Mensajes. Nada de esto se guarda.'}
        </p>
        <figure className="ad-vista">
          <figcaption className="j-subetiqueta">Así le llega</figcaption>
          <blockquote className="ad-mensaje">{cuerpo}</blockquote>
        </figure>
        {esDireccionLocal(location.hostname) && (
          <p className="ad-ayuda error" role="note">
            Abriste el panel desde {location.host}: ese enlace solo lo abre este dispositivo. Entra al panel desde el dominio de la invitación (el de Vercel) y manda desde ahí.
          </p>
        )}
        <div className="ad-fila-botones">
          {telefonoMalo ? (
            <button type="button" className="primario" disabled>
              Mandar por SMS
            </button>
          ) : (
            <a className="primario" href={enlaceSms(e164, cuerpo)}>
              Mandar por SMS
            </a>
          )}
          {puedeCompartir && (
            <button type="button" className="secundario" onClick={() => void compartir()}>
              Compartir…
            </button>
          )}
          <button type="button" className="secundario" onClick={() => void copiar(cuerpo, avisar, 'Mensaje copiado')}>
            Copiar mensaje
          </button>
          <button type="button" className="secundario" onClick={() => void copiar(enlace, avisar, 'Enlace copiado')}>
            Copiar enlace
          </button>
        </div>
      </div>
    </Seccion>
  )
}
