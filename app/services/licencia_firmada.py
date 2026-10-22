# COPIA de safemetrics_consola_backend/app/firma/licencia.py. Si cambia allá,
# se copia aquí igual: los dos lados tienen que leer el mismo formato.
"""Formato de la licencia: `contenido.firma`, los dos en base64url.

Se firman los BYTES de la parte `contenido` tal como viajan (igual que JWS),
así no hay que preocuparse de cómo cada lado ordena el JSON.

Firma ECDSA P-256 con SHA-256, en DER. Es lo que devuelve AWS KMS con
ECDSA_SHA_256 y lo que produce `cryptography`.

Este archivo solo depende de `cryptography`: en el paso 2 se copia tal cual
al backend de la instalación para verificar las licencias que recibe.
"""
import base64
import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# 2: manual maestro v4 (identidad, canal, plan, módulos y créditos con sus
# tarifas). La 1 ya no se emite y no hay instalaciones que la usen.
VERSION_FORMATO = 2


class LicenciaInvalida(Exception):
    pass


def b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def b64url_decode(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def armar(contenido: dict, firmar) -> str:
    """`firmar(bytes) -> bytes` es el firmador (local o KMS)."""
    parte = b64url(json.dumps(contenido, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return f"{parte}.{b64url(firmar(parte.encode('ascii')))}"


def verificar(
    token: str,
    clave_publica_pem: bytes,
    *,
    instalacion: str | None = None,
    secuencia_minima: int | None = None,
    ahora: datetime | None = None,
) -> dict:
    """Devuelve el contenido si la licencia es auténtica. Lanza LicenciaInvalida
    si la firma no cuadra, si es de otra instalación o si es más vieja que la
    que ya se tenía.

    NO lanza por vencida: el vencimiento lo maneja la instalación con su
    política de gracia (7 días normal, 7-14 avisos, luego solo frena lo
    nuevo). Para eso devuelve `vencida` dentro del resultado."""
    try:
        parte, firma = token.split(".")
        datos = parte.encode("ascii")
        firma_bytes = b64url_decode(firma)
    except (ValueError, UnicodeEncodeError) as e:
        raise LicenciaInvalida("formato incorrecto") from e

    clave = serialization.load_pem_public_key(clave_publica_pem)
    if not isinstance(clave, ec.EllipticCurvePublicKey):
        raise LicenciaInvalida("la clave pública no es ECDSA")
    try:
        clave.verify(firma_bytes, datos, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise LicenciaInvalida("firma inválida") from e

    contenido = json.loads(b64url_decode(parte))
    if contenido.get("v") != VERSION_FORMATO:
        raise LicenciaInvalida(f"versión de formato no soportada: {contenido.get('v')}")
    if instalacion is not None and contenido.get("instalacion") != instalacion:
        raise LicenciaInvalida("la licencia es de otra instalación")
    if secuencia_minima is not None and contenido["secuencia"] < secuencia_minima:
        raise LicenciaInvalida("licencia más vieja que la vigente")

    ahora = ahora or datetime.now(timezone.utc)
    contenido["vencida"] = datetime.fromisoformat(contenido["expira"]) <= ahora
    return contenido
