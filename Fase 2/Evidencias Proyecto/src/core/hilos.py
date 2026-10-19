"""Utilidad para iniciar QThread sin que se destruyan en marcha."""

_HILOS_RETENIDOS = set()


def iniciar_hilo_retenido(hilo):
    """Inicia el hilo y lo mantiene referenciado hasta que su señal `finished`
    confirma que terminó de verdad. La señal con el resultado llega antes del
    cierre del hilo; si en ese intervalo se suelta o reemplaza la referencia
    (o se destruye la pantalla que lo creó), Qt destruye el QThread en marcha y
    la aplicación se cierra ("QThread: Destroyed while thread is still running")."""
    senal = getattr(hilo, 'finished', None)
    if senal is not None:
        _HILOS_RETENIDOS.add(hilo)
        senal.connect(lambda h=hilo: _HILOS_RETENIDOS.discard(h))
    hilo.start()
    return hilo
