"""Reporte a la consola de Safemetrics (paso 2 del manual de la consola).

Cada 6 h la instalación le manda a la consola cuánto ocupa y recibe a cambio
la licencia firmada. La licencia se verifica con la clave pública empaquetada
(app/core/licencia_consola_publica.pem) y se guarda en token_account.

Desde la licencia v2 (manual maestro v4) trae además la identidad de la
empresa, el canal, el plan, los módulos habilitados y las tarifas de crédito,
que reemplazan a las escritas en el código. El logotipo se baja aparte, solo
cuando cambia su huella.

SOLO MIDE: no bloquea nada. Si la consola no responde se anota el error y se
sigue con la licencia que había; la política de gracia (7 / 14 días) se aplica
cuando se active el bloqueo (paso 5).

Variables de entorno (sin ellas la tarea no se programa):
  CONSOLA_URL                 p. ej. https://admin.safemetrics.co
  CONSOLA_CLAVE_INSTALACION   inst_xxx.secreto, la que entrega la consola
"""
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.endpoints.tokens import conteos, ocupado_de, por_formato, por_usuario, tarifas
from app.services.licencia_firmada import LicenciaInvalida, verificar

logger = logging.getLogger(__name__)

CONSOLA_URL = os.getenv("CONSOLA_URL", "").rstrip("/")
CONSOLA_CLAVE = os.getenv("CONSOLA_CLAVE_INSTALACION", "")
VERSION_APP = os.getenv("APP_VERSION", "")

# La clave pública va DENTRO de la app; no se descarga de la consola, porque
# entonces cualquiera podría hacerse pasar por ella.
_CLAVE_PUBLICA = Path(__file__).resolve().parent.parent / "core" / "licencia_consola_publica.pem"

# Para que dos procesos no reporten a la vez (número arbitrario, fijo).
_CANDADO = 7_310_2026


def configurado() -> bool:
    return bool(CONSOLA_URL and CONSOLA_CLAVE and "." in CONSOLA_CLAVE)


def _senales(db: Session) -> dict:
    """Lo que la consola necesita para sus alertas de fraude: altas y bajas
    de los últimos 30 días, y usuarios dados de baja y vueltos a crear (mismo
    correo). La puntuación la calcula la consola, no la instalación."""
    por_tipo = db.execute(text("""
        SELECT entidad_tipo, accion, count(*) AS n
        FROM token_events
        WHERE ocurrido_en > now() - interval '30 days'
        GROUP BY 1, 2
    """)).all()
    ciclos = db.execute(text("""
        SELECT count(*) FROM token_events b
        WHERE b.entidad_tipo = 'usuario' AND b.accion = 'libera'
          AND b.ocurrido_en > now() - interval '30 days'
          AND EXISTS (
              SELECT 1 FROM token_events a
              WHERE a.entidad_tipo = 'usuario' AND a.accion = 'ocupa'
                AND a.detalle = b.detalle AND a.ocurrido_en > b.ocurrido_en
          )
    """)).scalar()
    return {
        "eventos_30d": {f"{t}_{a}": n for t, a, n in por_tipo},
        "ciclos_usuario_30d": ciclos,
    }


def _detalle(db: Session) -> dict:
    """Los 20 formatos y los 20 usuarios que más ocupan, para que la consola
    muestre el consumo sin entrar a esta base. Se llaman las mismas consultas
    del panel /home/tokens (sus parámetros de FastAPI se pasan a mano).

    De los usuarios SOLO va el id y sus cifras: nombre y correo son datos
    personales del cliente y no salen de su servidor."""
    formatos = por_formato(limite=20, db=db, current_user=None)["items"]
    usuarios = por_usuario(limite=20, db=db, current_user=None)["items"]
    return {
        "por_formato": [
            {"id": f["id"], "titulo": (f["title"] or "")[:300], "campos": f["campos"], "tokens": f["tokens"]}
            for f in formatos
        ],
        "por_usuario": [
            {"id": u["id"], "formatos": u["formatos"], "campos": u["campos"],
             "movimientos": u["movimientos"], "tokens": u["tokens"]}
            for u in usuarios
        ],
    }


def reportar(db: Session) -> dict:
    """Reporta y guarda la licencia. Devuelve un resumen; si falla, lanza
    después de dejar el error anotado en token_account."""
    if not configurado():
        raise RuntimeError("Falta CONSOLA_URL o CONSOLA_CLAVE_INSTALACION")
    if not db.execute(text("SELECT pg_try_advisory_xact_lock(:c)"), {"c": _CANDADO}).scalar():
        return {"omitido": "otro proceso está reportando"}

    cuenta = db.execute(text("SELECT licencia_secuencia FROM token_account WHERE id = 1")).first()
    secuencia_local = cuenta[0] if cuenta else None
    desglose = conteos(db)
    # Con las tarifas de la licencia que se tiene: la consola revisa el
    # reporte con las de esa misma licencia.
    ocupado = ocupado_de(desglose, tarifas(db))
    ahora = datetime.now(timezone.utc)

    try:
        r = httpx.post(
            f"{CONSOLA_URL}/instalaciones/reporte",
            headers={"Authorization": f"Bearer {CONSOLA_CLAVE}"},
            json={
                "ocupado": ocupado, "desglose": desglose, "version_app": VERSION_APP or None,
                "licencia_secuencia": secuencia_local, "senales": _senales(db),
                "detalle": _detalle(db),
                "generado_en": ahora.isoformat(),
            },
            timeout=20,
        )
        r.raise_for_status()
        lic = verificar(
            r.json()["licencia"], _CLAVE_PUBLICA.read_bytes(),
            instalacion=CONSOLA_CLAVE.split(".", 1)[0],
            secuencia_minima=secuencia_local,
        )
    except (httpx.HTTPError, LicenciaInvalida, KeyError, ValueError) as e:
        error = f"{type(e).__name__}: {e}"[:500]
        db.execute(text("""
            INSERT INTO token_account (id, reporte_intentado_en, reporte_error) VALUES (1, :t, :e)
            ON CONFLICT (id) DO UPDATE SET reporte_intentado_en = :t, reporte_error = :e
        """), {"t": ahora, "e": error})
        db.commit()
        raise

    creditos = lic["creditos"]
    contenido = {k: v for k, v in lic.items() if k != "vencida"}
    db.execute(text("""
        INSERT INTO token_account (
            id, tokens_totales, licencia_firma, licencia_emitida_en, licencia_expira_en,
            licencia_secuencia, licencia_estado, bloqueo_activo, verificado_en,
            reporte_intentado_en, reporte_error, actualizado_en,
            licencia_contenido, tarifas, creditos_saldo
        ) VALUES (1, :tot, :firma, :emi, :exp, :sec, :est, :blq, :t, :t, NULL, :t,
                  CAST(:cont AS jsonb), CAST(:tar AS jsonb), :saldo)
        ON CONFLICT (id) DO UPDATE SET
            tokens_totales = :tot, licencia_firma = :firma, licencia_emitida_en = :emi,
            licencia_expira_en = :exp, licencia_secuencia = :sec, licencia_estado = :est,
            bloqueo_activo = :blq, verificado_en = :t, reporte_intentado_en = :t,
            reporte_error = NULL, actualizado_en = :t,
            licencia_contenido = CAST(:cont AS jsonb), tarifas = CAST(:tar AS jsonb),
            creditos_saldo = :saldo
    """), {
        "tot": creditos["comprados"], "firma": r.json()["licencia"],
        "emi": datetime.fromisoformat(lic["emitida"]), "exp": datetime.fromisoformat(lic["expira"]),
        "sec": lic["secuencia"], "est": lic["estado"], "blq": lic["bloqueo_activo"], "t": ahora,
        "cont": json.dumps(contenido, ensure_ascii=False), "tar": json.dumps(creditos["tarifas"]),
        "saldo": creditos["saldo"],
    })
    db.commit()
    logo = _sincronizar_logo(db, (lic.get("empresa") or {}).get("logo_sha256"))
    return {
        "ocupado": ocupado, "creditos_comprados": creditos["comprados"], "saldo": creditos["saldo"],
        "plan": lic["plan"], "canal": lic["canal"], "modulos": lic["modulos"],
        "identificador": lic["identificador"], "logo": logo,
        "secuencia": lic["secuencia"], "estado": lic["estado"], "expira": lic["expira"],
    }


def _sincronizar_logo(db: Session, huella: str | None) -> str:
    """Deja en token_account el logotipo que dice la licencia. Lo baja de la
    consola solo si la huella cambió, y lo descarta si no cuadra con ella.
    Un fallo aquí no tumba el reporte: se reintenta en el siguiente."""
    actual = db.execute(text("SELECT empresa_logo FROM token_account WHERE id = 1")).scalar()
    actual_huella = hashlib.sha256(bytes(actual)).hexdigest() if actual is not None else None
    if huella == actual_huella:
        return "sin cambios"
    if huella is None:
        db.execute(text("UPDATE token_account SET empresa_logo = NULL, empresa_logo_tipo = NULL WHERE id = 1"))
        db.commit()
        return "retirado"
    try:
        r = httpx.get(f"{CONSOLA_URL}/instalaciones/logo",
                      headers={"Authorization": f"Bearer {CONSOLA_CLAVE}"}, timeout=20)
        r.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("[consola] no se pudo bajar el logotipo: %s", e)
        return "pendiente"
    if hashlib.sha256(r.content).hexdigest() != huella:
        logger.warning("[consola] el logotipo bajado no cuadra con la huella de la licencia")
        return "pendiente"
    tipo = r.headers.get("content-type", "").split(";")[0].strip()
    db.execute(text("UPDATE token_account SET empresa_logo = :b, empresa_logo_tipo = :t WHERE id = 1"),
               {"b": r.content, "t": tipo})
    db.commit()
    return "actualizado"


def tarea_programada() -> None:
    """La que corre APScheduler. Nunca lanza: un fallo de red no puede tumbar
    el scheduler, y el error ya quedó en token_account."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        resultado = reportar(db)
        logger.info("[consola] reporte enviado: %s", resultado)
    except Exception as e:
        db.rollback()
        logger.warning("[consola] no se pudo reportar: %s", e)
    finally:
        db.close()
