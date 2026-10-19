"""Instrumentacion temporal de rendimiento (Fase 0 de la auditoria de
rendimiento, 17-09-2026). Sirve solo para obtener una linea base de tiempos
(startup, data_ready, guardados, apertura de modulos) y poder comparar antes/
despues de cada fase de optimizacion -- no es un mecanismo de logging
permanente ni reemplaza a logs/sistema.log.

Uso:
    from src.core.perf_log import medir
    with medir("data_ready -> Vista General cargada"):
        ... codigo a medir ...

Imprime por stdout (no escribe a disco, para no agregar mas I/O al problema
que se esta midiendo). Se puede desactivar por completo poniendo
PERF_LOG_ACTIVO en False, sin tener que quitar los `with medir(...)` ya
colocados."""

import contextlib
import time

PERF_LOG_ACTIVO = True


@contextlib.contextmanager
def medir(etiqueta, hilo="UI"):
    # `hilo`: etiqueta informativa ("UI" o "WORKER") para distinguir en el
    # propio log si el bloque medido corre en el hilo principal de Qt o
    # dentro de un QThread -- no cambia ningun comportamiento, solo el texto
    # impreso (auditoria de rendimiento, continuacion 17-09-2026).
    if not PERF_LOG_ACTIVO:
        yield
        return
    inicio = time.perf_counter()
    try:
        yield
    finally:
        duracion_ms = (time.perf_counter() - inicio) * 1000
        print(f"[PERF][{hilo}] {etiqueta}: {duracion_ms:.0f} ms")
