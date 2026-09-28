"""Caché en memoria para los listados que casi nunca cambian.

Qué se guarda
─────────────
Solo listados chicos y muy pedidos: los formatos disponibles, la lista de
formatos, los conteos de preguntas por carpeta y los formatos del selector de
pregunta de origen. Son unos pocos KB cada uno y se piden en cada visita a la
pantalla de Campos y en cada apertura de sus modales.

Por qué
───────
Aunque las consultas ya son rápidas, cada petición sigue costando un viaje a la
base. Cuando el backend y la base no están en la misma máquina, ese viaje pesa
más que la consulta. Y si varias personas abren la misma pantalla, se repite el
mismo trabajo para devolver exactamente lo mismo.

Lo que NO se guarda
───────────────────
Nada que dependa del usuario ni que cambie a cada rato: respuestas, respuestas
relacionadas, correlaciones, consolidados de movimientos. Una lista de formatos
vieja por un minuto es un detalle; una respuesta vieja, no.

Cómo caduca
───────────
Por tiempo (60 segundos por defecto) y por invalidación explícita: crear, editar
o borrar una pregunta o un formato limpia la caché de una. Así, en el caso normal
—que es abrir la pantalla— el dato está fresco, y en el peor caso queda un minuto
de retraso.

Ojo con los workers
───────────────────
Cada worker de uvicorn tiene su propia copia. Eso está bien para esto: son datos
de solo lectura y el TTL es corto. No sirve como caché compartida ni para
coordinar nada entre procesos.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

_TTL_POR_DEFECTO = 60.0

_candado = threading.Lock()
_datos: dict[str, tuple[float, Any]] = {}


def obtener(clave: str) -> Optional[Any]:
    """El valor guardado, o None si no está o ya caducó."""
    with _candado:
        entrada = _datos.get(clave)
        if entrada is None:
            return None
        caduca, valor = entrada
        if caduca < time.monotonic():
            _datos.pop(clave, None)
            return None
        return valor


def guardar(clave: str, valor: Any, ttl: float = _TTL_POR_DEFECTO) -> Any:
    with _candado:
        _datos[clave] = (time.monotonic() + ttl, valor)
    return valor


def con_cache(clave: str, calcular: Callable[[], Any], ttl: float = _TTL_POR_DEFECTO) -> Any:
    """Devuelve lo guardado o lo calcula y lo guarda.

    `calcular` puede ejecutarse dos veces si dos peticiones llegan a la vez con
    la caché vacía. No se bloquea a propósito: son consultas de milisegundos y
    prefiero no tener un candado retenido mientras se habla con la base.
    """
    valor = obtener(clave)
    if valor is not None:
        return valor
    return guardar(clave, calcular(), ttl)


def invalidar(prefijo: str | None = None) -> None:
    """Borra todo, o solo las claves que empiecen por `prefijo`."""
    with _candado:
        if prefijo is None:
            _datos.clear()
            return
        for clave in [k for k in _datos if k.startswith(prefijo)]:
            _datos.pop(clave, None)
