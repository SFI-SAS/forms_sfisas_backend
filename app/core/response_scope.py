"""Qué respuestas cuentan como diligenciamiento.

Desde que un aprobador escribe en SU PROPIA respuesta (`Response.parent_response_id`
apuntando a la del diligenciador), la tabla `responses` tiene dos clases de fila:

  · las de diligenciamiento — `parent_response_id IS NULL`, las de siempre;
  · las de aprobador — cuelgan de una de las anteriores.

Todo listado, conteo o export de "las respuestas de este formato" se refiere a
las PRIMERAS. Este módulo existe para que ese filtro se escriba igual en todas
partes y sea fácil de encontrar.

    query = only_submissions(db.query(Response).filter(Response.form_id == form_id))
    stmt  = select(Response.id).where(Response.form_id == form_id, IS_SUBMISSION)

Para leer una respuesta COMPLETA (lo del diligenciador más lo que respondieron
sus aprobadores) está `response_tree_ids`.
"""

from typing import List

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import Response

# Expresión reutilizable para where()/filter().
IS_SUBMISSION = Response.parent_response_id.is_(None)

# Marca de "sí quiero las respuestas de aprobador" para las pocas consultas que
# las necesitan. Ver `include_approver_responses()`.
_OPT_IN = "include_approver_responses"


def only_submissions(query):
    """Deja fuera las respuestas de aprobador."""
    return query.filter(IS_SUBMISSION)


def include_approver_responses(query):
    """Desactiva el filtro global para ESTA consulta.

    Solo para lo que de verdad las necesita: la lista "mis respuestas como
    aprobador" y la lectura de una respuesta completa.
    """
    return query.execution_options(**{_OPT_IN: True})


@event.listens_for(Session, "do_orm_execute")
def _excluir_respuestas_de_aprobador(execute_state):
    """Filtro global: una consulta de `Response` no ve las de aprobador.

    Hay ~80 consultas que listan o cuentan respuestas (listados, exports,
    movimientos, tableros, correos). Ir a ponerles el filtro a mano dejaría
    huecos —y cada hueco es un conteo mal en una pantalla— así que se aplica
    aquí, una sola vez, a todo SELECT de la entidad.

    Quien las necesite pide `include_approver_responses(query)`.
    """
    if not execute_state.is_select:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        # Cargas perezosas de una fila que YA se entregó: filtrarlas rompería
        # la lectura de una respuesta de aprobador que alguien ya tiene.
        return
    if execute_state.execution_options.get(_OPT_IN):
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            Response,
            lambda cls: cls.parent_response_id.is_(None),
            include_aliases=True,
        )
    )


def response_tree_ids(db, response_id: int) -> List[int]:
    """La respuesta y las de sus aprobadores.

    Es lo que hay que consultar para mostrar el formato completo: las answers
    del diligenciador viven en la primera y las de cada aprobador en la suya.
    """
    hijos = [
        row[0]
        for row in include_approver_responses(
            db.query(Response.id).filter(Response.parent_response_id == response_id)
        ).all()
    ]
    return [response_id] + hijos
