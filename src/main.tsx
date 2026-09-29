import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Invitacion } from './invitacion/Invitacion'
import './styles/index.css'

const raiz = document.getElementById('raiz')
if (!raiz) throw new Error('Falta #raiz en index.html')

createRoot(raiz).render(
  <StrictMode>
    <Invitacion />
  </StrictMode>,
)
