"""Un try que lanza HTTPException y tiene `except Exception` debe dejarla pasar.

Si no, un 404/403 intencional sale como 500 genérico (pasó en set_reconsideration y otros 6).
"""
import ast
import glob
import os

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


def _tragan_http_exception():
    malos = []
    for ruta in glob.glob(os.path.join(APP, "**", "*.py"), recursive=True):
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Try):
                continue
            tipos = [ast.unparse(h.type) if h.type else "" for h in nodo.handlers]
            if any("HTTPException" in t for t in tipos):
                continue
            if not any(t in ("", "Exception", "BaseException") for t in tipos):
                continue
            lanza = any(isinstance(n, ast.Raise) and n.exc is not None and "HTTPException" in ast.unparse(n.exc)[:20]
                        for s in nodo.body for n in ast.walk(s))
            if lanza:
                malos.append(f"{os.path.relpath(ruta, APP)}:{nodo.lineno}")
    return malos


def test_ningun_try_convierte_un_4xx_en_500():
    assert _tragan_http_exception() == []
