/** Doble filete de plata con esquinas grabadas. En las tarjetas `.dibujo` los filetes se dibujan al llegar. */
export function Marco() {
  return (
    <>
      <span className="marco" aria-hidden="true">
        <span className="m-h" />
        <span className="m-v" />
      </span>
      <span className="esquinas" aria-hidden="true" />
    </>
  )
}
