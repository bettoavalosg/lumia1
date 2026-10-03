"""Genera el par de llaves VAPID para las notificaciones push. Usa openssl (viene con macOS y Linux); no instala nada.

    python scripts/generar_vapid.py

La pública va al front (VITE_VAPID_PUBLIC_KEY, en Vercel) y la privada a la Edge Function (supabase secrets set).
La privada no se comparte ni se sube al repo.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys


def b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b'=').decode()


def openssl(*args: str, entrada: bytes | None = None) -> bytes:
    r = subprocess.run(['openssl', *args], input=entrada, capture_output=True)
    if r.returncode:
        sys.exit(f'openssl falló: {r.stderr.decode().strip()}')
    return r.stdout


def main() -> None:
    if not shutil.which('openssl'):
        sys.exit('No encontré openssl. Instálalo o corre: npx web-push generate-vapid-keys')
    pem = openssl('ecparam', '-name', 'prime256v1', '-genkey', '-noout')
    privada_der = openssl('ec', '-outform', 'DER', entrada=pem)
    publica_der = openssl('ec', '-pubout', '-outform', 'DER', entrada=pem)
    # DER de una llave EC P-256: el escalar privado son 32 bytes tras el encabezado (04 20); la pública son los últimos 65 (04 + X + Y).
    indice = privada_der.index(b'\x04\x20') + 2
    privada = privada_der[indice : indice + 32]
    publica = publica_der[-65:]
    assert len(privada) == 32 and len(publica) == 65 and publica[0] == 4
    print('Llaves VAPID (guarda la privada; no la compartas):\n')
    print(f'VITE_VAPID_PUBLIC_KEY={b64url(publica)}   # en Vercel (Settings → Environment Variables)')
    print(f'VAPID_PUBLIC_KEY={b64url(publica)}   # en la Edge Function')
    print(f'VAPID_PRIVATE_KEY={b64url(privada)}   # en la Edge Function')
    print('\nDespués:  supabase secrets set VAPID_PUBLIC_KEY=… VAPID_PRIVATE_KEY=… VAPID_SUBJECT=mailto:tu@correo.com PUSH_SECRET=<algo-largo>')


if __name__ == '__main__':
    main()
