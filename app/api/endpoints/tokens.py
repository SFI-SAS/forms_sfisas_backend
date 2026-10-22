"""
Créditos (antes "tokens") — FASE DE MEDICIÓN.

La unidad se llama crédito desde el manual maestro v4 (Andrés, 20-oct-2026),
para no confundirla con los tokens del motor de ArIA. Las rutas y las tablas
conservan el nombre viejo: las migraciones solo agregan, nunca renombran.

Este módulo SOLO MIDE. No bloquea ninguna acción: ni crear usuarios, ni
formatos, ni vincular campos. Existe para que el administrador vea el consumo
y para poder calibrar los precios con datos reales antes de activar el cobro.

Modelo: los tokens son CAPACIDAD OCUPADA, no consumo. Lo que existe ocupa; lo
que se borra libera. No hay "gasto histórico" que perseguir, así que el ocupado
se CALCULA EN VIVO contando lo que hay. Es siempre correcto por construcción:
no puede desincronizarse como un contador incremental.

Ver el diseño completo en DISENO_tokens_licenciamiento.md (raíz del proyecto).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database import get_db
from app.models import User, UserType

router = APIRouter()

# ── Tarifas ──────────────────────────────────────────────────────────────────
# Las fija la consola y llegan en la licencia (token_account.tarifas). Estos
# valores solo rigen mientras no haya licencia, y son los mismos que siembra la
# migración 2026-10-20 y la función SQL token_tarifa().
TOKENS_USUARIO    = 50
TOKENS_FORMATO    = 20
TOKENS_MOVIMIENTO = 20
TOKENS_VINCULO    = 2   # por cada par campo↔formato
_TARIFAS_INICIALES = {"usuario": TOKENS_USUARIO, "formato": TOKENS_FORMATO,
                      "movimiento": TOKENS_MOVIMIENTO, "campo": TOKENS_VINCULO}

# Crear un campo suelto no cuesta. Tampoco los elementos que no son preguntas
# (títulos, separadores, imágenes, layouts) ni los datos diligenciados.

_ADMIN = require_roles([UserType.admin])


def tarifas(db: Session) -> dict:
    """Créditos por usuario, formato, movimiento y campo: los de la última
    licencia, o los iniciales si todavía no hay."""
    try:
        guardadas = db.execute(text("SELECT tarifas FROM token_account WHERE id = 1")).scalar()
    except Exception:
        # Base sin la migración 2026-10-20.
        db.rollback()
        guardadas = None
    return {k: int((guardadas or {}).get(k, v)) for k, v in _TARIFAS_INICIALES.items()}


def ocupado_de(desglose: dict, t: dict) -> int:
    return (desglose["usuarios"] * t["usuario"] + desglose["formatos"] * t["formato"]
            + desglose["movimientos"] * t["movimiento"] + desglose["vinculos"] * t["campo"])


def conteos(db: Session) -> dict:
    """Cuántos hay de cada cosa que ocupa. Es también el desglose que se
    reporta a la consola (app/services/consola_reporte.py).

    Solo ocupa el usuario habilitado: dar de baja libera (manual maestro 4.2).
    Un campo vinculado dos veces al mismo formato cuenta una sola: el doble
    vínculo es un error de guardado, no algo que el cliente tenga montado."""
    return dict(db.execute(text("""
        SELECT
            (SELECT count(*) FROM users WHERE is_active) AS usuarios,
            (SELECT count(*) FROM forms)             AS formatos,
            (SELECT count(*) FROM forms_movimientos) AS movimientos,
            (SELECT count(*) FROM (SELECT DISTINCT form_id, question_id
                                   FROM form_questions) v) AS vinculos
    """)).mappings().one())


def _ocupacion(db: Session) -> dict:
    """Cuenta la capacidad ocupada ahora mismo, en una sola consulta."""
    fila = conteos(db)
    t = tarifas(db)

    desglose = [
        {"concepto": "Usuarios habilitados", "cantidad": fila["usuarios"],
         "tarifa": t["usuario"],    "tokens": fila["usuarios"] * t["usuario"]},
        {"concepto": "Formatos",    "cantidad": fila["formatos"],
         "tarifa": t["formato"],    "tokens": fila["formatos"] * t["formato"]},
        {"concepto": "Movimientos", "cantidad": fila["movimientos"],
         "tarifa": t["movimiento"], "tokens": fila["movimientos"] * t["movimiento"]},
        {"concepto": "Campos en formatos", "cantidad": fila["vinculos"],
         "tarifa": t["campo"],      "tokens": fila["vinculos"] * t["campo"]},
    ]
    return {"desglose": desglose, "ocupado": sum(d["tokens"] for d in desglose), "tarifas": t}


@router.get("/summary")
def resumen(db: Session = Depends(get_db), current_user: User = Depends(_ADMIN)):
    """Cuánto hay contratado, cuánto está ocupado y cuánto queda."""
    cuenta = db.execute(text("""
        SELECT tokens_totales, bloqueo_activo, licencia_expira_en, verificado_en,
               licencia_estado, reporte_intentado_en, reporte_error,
               licencia_contenido, creditos_saldo
        FROM token_account WHERE id = 1
    """)).mappings().first()

    lic = (cuenta["licencia_contenido"] if cuenta else None) or {}
    creditos = lic.get("creditos") or {}
    plan = lic.get("plan")
    oc = _ocupacion(db)
    ocupado = oc["ocupado"]
    # El plan gratuito no tiene saldo comprado: tiene un tope de ocupación
    # (manual maestro 5). Contra eso se mide.
    if plan == "gratuito" and creditos.get("tope") is not None:
        totales = int(creditos["tope"])
    else:
        totales = int(cuenta["tokens_totales"]) if cuenta else 0
    t = oc["tarifas"]

    return {
        "tokens_totales": totales,
        "tokens_ocupados": ocupado,
        "tokens_disponibles": totales - ocupado,
        # Si aún no se ha cargado ninguna licencia, el porcentaje no significa
        # nada; se devuelve None en vez de dividir por cero.
        "porcentaje_uso": round(ocupado * 100.0 / totales, 1) if totales > 0 else None,
        "desglose": oc["desglose"],
        # En fase de medición esto va en False: se mide, no se bloquea.
        "bloqueo_activo": bool(cuenta["bloqueo_activo"]) if cuenta else False,
        "licencia_expira_en": cuenta["licencia_expira_en"] if cuenta else None,
        "verificado_en": cuenta["verificado_en"] if cuenta else None,
        # Lo que dice la última licencia de la consola y cómo salió el último
        # intento de reportarle (app/services/consola_reporte.py).
        "licencia_estado": cuenta["licencia_estado"] if cuenta else None,
        "reporte_intentado_en": cuenta["reporte_intentado_en"] if cuenta else None,
        "reporte_error": cuenta["reporte_error"] if cuenta else None,
        "tarifas": {
            "usuario": t["usuario"],
            "formato": t["formato"],
            "movimiento": t["movimiento"],
            "campo_en_formato": t["campo"],
        },
        # Lo demás que trae la licencia v2 (manual maestro 8). None mientras
        # la consola no haya entregado ninguna.
        "identificador": lic.get("identificador"),
        "empresa": (lic.get("empresa") or {}).get("nombre"),
        "canal": lic.get("canal"),
        "plan": plan,
        "modulos": lic.get("modulos") or [],
        "creditos_saldo": cuenta["creditos_saldo"] if cuenta else None,
    }


@router.post("/reportar-ahora")
def reportar_ahora(db: Session = Depends(get_db), current_user: User = Depends(_ADMIN)):
    """Reporta a la consola sin esperar las 6 h y trae la licencia. Sirve para
    comprobar al instalar que la instalación se comunica con la consola."""
    from fastapi import HTTPException

    from app.services import consola_reporte  # importa este módulo: evita el ciclo

    if not consola_reporte.configurado():
        raise HTTPException(status_code=409, detail="La instalación no tiene configurada la consola")
    # Un fallo de la consola no es un error de esta API: va como respuesta
    # normal, porque el manejador global oculta el detalle de los 5xx y el
    # administrador necesita ver el motivo.
    try:
        return {"ok": True, **consola_reporte.reportar(db)}
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}


@router.get("/by-form")
def por_formato(
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Qué formatos ocupan más tokens. El coste de un formato es su tarifa base
    más 2 por cada campo vinculado, así que los formatos con muchos campos
    dominan la factura aunque nadie lo note."""
    t = tarifas(db)
    filas = db.execute(text("""
        SELECT f.id,
               f.title,
               f.is_enabled,
               u.name                            AS creador,
               count(DISTINCT fq.question_id)               AS campos,
               :base + count(DISTINCT fq.question_id) * :vinc AS tokens
        FROM forms f
        LEFT JOIN form_questions fq ON fq.form_id = f.id
        LEFT JOIN users u           ON u.id = f.user_id
        GROUP BY f.id, f.title, f.is_enabled, u.name
        ORDER BY tokens DESC
        LIMIT :limite
    """), {"base": t["formato"], "vinc": t["campo"], "limite": limite}).mappings().all()

    return {"items": [dict(f) for f in filas]}


@router.get("/by-user")
def por_usuario(
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Qué usuario ha generado más ocupación.

    OJO con cómo se atribuye: se cuenta lo que cada usuario CREÓ (sus formatos
    con sus campos, y sus movimientos), más lo que ocupa él mismo si está
    habilitado. Los usuarios NO se atribuyen a quien los dio de alta, porque
    la tabla `users` no guarda quién creó a quién.
    """
    t = tarifas(db)
    filas = db.execute(text("""
        SELECT u.id,
               u.name,
               u.email,
               coalesce(f.formatos, 0)                   AS formatos,
               coalesce(f.campos, 0)                     AS campos,
               coalesce(m.movimientos, 0)                AS movimientos,
               CASE WHEN u.is_active THEN :propio ELSE 0 END
                 + coalesce(f.formatos, 0) * :base
                 + coalesce(f.campos, 0)   * :vinc
                 + coalesce(m.movimientos, 0) * :mov     AS tokens
        FROM users u
        LEFT JOIN (
            SELECT f.user_id,
                   count(DISTINCT f.id) AS formatos,
                   count(DISTINCT CASE WHEN fq.id IS NOT NULL
                                       THEN (fq.form_id, fq.question_id) END) AS campos
            FROM forms f
            LEFT JOIN form_questions fq ON fq.form_id = f.id
            GROUP BY f.user_id
        ) f ON f.user_id = u.id
        LEFT JOIN (
            SELECT user_id, count(*) AS movimientos
            FROM forms_movimientos GROUP BY user_id
        ) m ON m.user_id = u.id
        ORDER BY tokens DESC
        LIMIT :limite
    """), {"propio": t["usuario"], "base": t["formato"],
           "vinc": t["campo"], "mov": t["movimiento"],
           "limite": limite}).mappings().all()

    return {"items": [dict(f) for f in filas]}


@router.get("/most-reused-fields")
def campos_mas_reutilizados(
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Campos usados en varios formatos. Se cobra el par campo↔formato, así que
    un mismo campo en 5 formatos ocupa 10 tokens. Es la parte del modelo que
    más preguntas genera al cliente: conviene poder mostrarla."""
    filas = db.execute(text("""
        SELECT q.id,
               q.question_text,
               count(DISTINCT fq.form_id)          AS formatos,
               count(DISTINCT fq.form_id) * :vinc  AS tokens
        FROM form_questions fq
        JOIN questions q ON q.id = fq.question_id
        GROUP BY q.id, q.question_text
        HAVING count(DISTINCT fq.form_id) > 1
        ORDER BY tokens DESC
        LIMIT :limite
    """), {"vinc": tarifas(db)["campo"], "limite": limite}).mappings().all()

    return {"items": [dict(f) for f in filas]}


@router.get("/events")
def eventos(
    limite: int = Query(100, ge=1, le=1000),
    entidad_tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Historial de altas y bajas de capacidad.

    En la fase de medición esta tabla está VACÍA: los enganches que la llenan
    (al crear/borrar usuarios, formatos, movimientos y vínculos) son el
    siguiente paso. El endpoint existe ya para que el panel no tenga que
    cambiar cuando empiecen a llegar datos.
    """
    filtro = "WHERE e.entidad_tipo = :tipo" if entidad_tipo else ""
    filas = db.execute(text(f"""
        SELECT e.id, e.ocurrido_en, e.entidad_tipo, e.entidad_id, e.accion,
               e.tokens, e.ocupado_despues, e.origen, e.detalle,
               u.name AS actor
        FROM token_events e
        LEFT JOIN users u ON u.id = e.actor_user_id
        {filtro}
        ORDER BY e.ocurrido_en DESC
        LIMIT :limite
    """), {"limite": limite, **({"tipo": entidad_tipo} if entidad_tipo else {})}).mappings().all()

    return {"items": [dict(f) for f in filas]}
