import 'react'

// Variables CSS en `style` (por ejemplo --i para el retraso de cada palabra) sin conversiones de tipo.
declare module 'react' {
  interface CSSProperties {
    [variable: `--${string}`]: string | number
  }
}
