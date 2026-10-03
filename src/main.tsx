import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Raiz } from './Raiz'
import './styles/index.css'

const raiz = document.getElementById('raiz')
if (!raiz) throw new Error('Falta #raiz en index.html')

createRoot(raiz).render(
  <StrictMode>
    <Raiz />
  </StrictMode>,
)
