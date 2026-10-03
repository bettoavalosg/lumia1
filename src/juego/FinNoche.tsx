import { Premios } from '../compartido/Premios'
import { useJuego } from '../servidor/hooks'
import '../styles/juego.css'

/** Se acabó la noche: el podio, los premios y un beso. */
export default function FinNoche({ alVerInvitacion }: { alVerInvitacion: () => void }) {
  const { e } = useJuego()
  return (
    <div className="juego fin-noche">
      <div className="bruma" aria-hidden="true" />
      <main className="j-escena">
        <section className="j-pantalla">
          <p className="j-etiqueta">Fin de la noche</p>
          <h1 className="j-titulo">Se acabó la noche.</h1>
          <p className="j-texto">Gracias por venir, por callar y por acusar. Esto es lo que dejó.</p>
          {e.ranking ? <Premios ranking={e.ranking} /> : <p className="j-texto">Nadie bebió. Sospechoso.</p>}
          <p className="j-firma">XOXO</p>
          <button type="button" className="j-enlace" onClick={alVerInvitacion}>
            Ver la invitación
          </button>
        </section>
      </main>
    </div>
  )
}
