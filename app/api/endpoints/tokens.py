"""
Tokens — FASE DE MEDICIÓN.

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
# Un único sitio donde viven los precios. Cambiar aquí cambia todo el cálculo.
TOKENS_USUARIO    = 50
TOKENS_FORMATO    = 20
TOKENS_MOVIMIENTO = 20
TOKENS_VINCULO    = 2   # por cada par campo↔formato

# Crear un campo suelto no cuesta. Tampoco los elementos que no son preguntas
# (títulos, separadores, imágenes, layouts) ni los datos diligenciados.

_ADMIN = require_roles([UserType.admin])


def _ocupacion(db: Session) -> dict:
    """Cuenta la capacidad ocupada ahora mismo, en una sola consulta."""
    fila = db.execute(text("""
        SELECT
            (SELECT count(*) FROM users)             AS usuarios,
            (SELECT count(*) FROM forms)             AS formatos,
            (SELECT count(*) FROM forms_movimientos) AS movimientos,
            (SELECT count(*) FROM form_questions)    AS vinculos
    """)).mappings().one()

    desglose = [
        {"concepto": "Usuarios",    "cantidad": fila["usuarios"],
         "tarifa": TOKENS_USUARIO,    "tokens": fila["usuarios"] * TOKENS_USUARIO},
        {"concepto": "Formatos",    "cantidad": fila["formatos"],
         "tarifa": TOKENS_FORMATO,    "tokens": fila["formatos"] * TOKENS_FORMATO},
        {"concepto": "Movimientos", "cantidad": fila["movimientos"],
         "tarifa": TOKENS_MOVIMIENTO, "tokens": fila["movimientos"] * TOKENS_MOVIMIENTO},
        {"concepto": "Campos en formatos", "cantidad": fila["vinculos"],
         "tarifa": TOKENS_VINCULO,    "tokens": fila["vinculos"] * TOKENS_VINCULO},
    ]
    return {"desglose": desglose, "ocupado": sum(d["tokens"] for d in desglose)}


@router.get("/summary")
def resumen(db: Session = Depends(get_db), current_user: User = Depends(_ADMIN)):
    """Cuánto hay contratado, cuánto está ocupado y cuánto queda."""
    cuenta = db.execute(text("""
        SELECT tokens_totales, bloqueo_activo, licencia_expira_en, verificado_en
        FROM token_account WHERE id = 1
    """)).mappings().first()

    totales = int(cuenta["tokens_totales"]) if cuenta else 0
    oc = _ocupacion(db)
    ocupado = oc["ocupado"]

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
        "tarifas": {
            "usuario": TOKENS_USUARIO,
            "formato": TOKENS_FORMATO,
            "movimiento": TOKENS_MOVIMIENTO,
            "campo_en_formato": TOKENS_VINCULO,
        },
    }


@router.get("/by-form")
def por_formato(
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Qué formatos ocupan más tokens. El coste de un formato es su tarifa base
    más 2 por cada campo vinculado, así que los formatos con muchos campos
    dominan la factura aunque nadie lo note."""
    filas = db.execute(text("""
        SELECT f.id,
               f.title,
               f.is_enabled,
               u.name                            AS creador,
               count(fq.id)                      AS campos,
               :base + count(fq.id) * :vinc      AS tokens
        FROM forms f
        LEFT JOIN form_questions fq ON fq.form_id = f.id
        LEFT JOIN users u           ON u.id = f.user_id
        GROUP BY f.id, f.title, f.is_enabled, u.name
        ORDER BY tokens DESC
        LIMIT :limite
    """), {"base": TOKENS_FORMATO, "vinc": TOKENS_VINCULO, "limite": limite}).mappings().all()

    return {"items": [dict(f) for f in filas]}


@router.get("/by-user")
def por_usuario(
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    """Qué usuario ha generado más ocupación.

    OJO con cómo se atribuye: se cuenta lo que cada usuario CREÓ (sus formatos
    con sus campos, y sus movimientos), más los 50 que ocupa él mismo por
    existir. Los usuarios NO se atribuyen a quien los dio de alta, porque la
    tabla `users` no guarda quién creó a quién.
    """
    filas = db.execute(text("""
        SELECT u.id,
               u.name,
               u.email,
               coalesce(f.formatos, 0)                   AS formatos,
               coalesce(f.campos, 0)                     AS campos,
               coalesce(m.movimientos, 0)                AS movimientos,
               :propio
                 + coalesce(f.formatos, 0) * :base
                 + coalesce(f.campos, 0)   * :vinc
                 + coalesce(m.movimientos, 0) * :mov     AS tokens
        FROM users u
        LEFT JOIN (
            SELECT f.user_id,
                   count(DISTINCT f.id) AS formatos,
                   count(fq.id)         AS campos
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
    """), {"propio": TOKENS_USUARIO, "base": TOKENS_FORMATO,
           "vinc": TOKENS_VINCULO, "mov": TOKENS_MOVIMIENTO,
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
               count(fq.id)              AS formatos,
               count(fq.id) * :vinc      AS tokens
        FROM form_questions fq
        JOIN questions q ON q.id = fq.question_id
        GROUP BY q.id, q.question_text
        HAVING count(fq.id) > 1
        ORDER BY tokens DESC
        LIMIT :limite
    """), {"vinc": TOKENS_VINCULO, "limite": limite}).mappings().all()

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
