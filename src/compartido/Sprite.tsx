import sprite from '../invitacion/svg/sprite.svg?raw'

/** Los símbolos que comparten todas las pantallas: el sello de cera (#cera) y el blasón (#blason). */
export function Sprite() {
  return <svg className="sprite" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: sprite }} />
}

/** El sello de cera, pequeño. */
export function Cera({ className = '' }: { className?: string }) {
  return (
    <svg className={`cera ${className}`} viewBox="0 0 240 240" aria-hidden="true" focusable="false">
      <use href="#cera" />
    </svg>
  )
}
