"""
AppLockCoordinator: traduce el estado por-archivo de FileLockMonitor en un
unico estado de aplicacion (NORMAL / BLOQUEADA).

No detecta nada por si mismo y no duplica ninguna logica de FileLockMonitor:
solo escucha su senal estado_cambiado(clave, ocupado) y agrega "¿hay al
menos uno de los archivos principales ocupado en este momento?" en un
booleano unico. FileLockMonitor sigue siendo la unica fuente de verdad
sobre el estado de cada archivo.

Ver Fase 5 (auditoria): esta capa es deliberadamente minima. La UI que
reacciona a este estado (alerta roja, boton "Cerrar Excel", indicador de
archivos ocupados) se agrega en fases posteriores; aqui solo se expone el
booleano agregado para que MainWindow pueda deshabilitar la interfaz.
"""
from PyQt6.QtCore import QObject, pyqtSignal


class AppLockCoordinator(QObject):
    """Agrega el estado de N archivos (reportado por FileLockMonitor) en un
    unico estado de aplicacion.

    Uso tipico:
        monitor = FileLockMonitor()  # o FileLockMonitorThread
        coordinator = AppLockCoordinator(monitor.estado_cambiado)
        coordinator.estado_app_cambiado.connect(mi_slot)

    `estado_app_cambiado(bool bloqueada)` se emite unicamente cuando el
    estado agregado realmente cambia (False->True o True->False), nunca en
    cada evento individual de FileLockMonitor -- si dos archivos se
    confirman ocupados, la señal se emite una sola vez (al primero), y solo
    vuelve a emitirse (con False) cuando el ULTIMO de los archivos
    ocupados se libera.

    `archivos_ocupados_cambiado()` (Fase 6) se emite cada vez que el
    CONJUNTO de archivos ocupados cambia, incluso si el booleano agregado
    no cambia -- ej. con dos archivos ocupados, si se libera solo uno, la
    app sigue bloqueada (estado_app_cambiado no se emite) pero la lista de
    archivos ocupados si cambio (esta señal si se emite), para que quien
    muestre esa lista en pantalla pueda mantenerla actualizada.
    """

    estado_app_cambiado = pyqtSignal(bool)
    archivos_ocupados_cambiado = pyqtSignal()

    def __init__(self, fuente_estado_cambiado):
        super().__init__()
        self._archivos_ocupados = set()
        self._bloqueada = False
        fuente_estado_cambiado.connect(self._on_archivo_estado_cambiado)

    def _on_archivo_estado_cambiado(self, clave, ocupado):
        antes = set(self._archivos_ocupados)
        if ocupado:
            self._archivos_ocupados.add(clave)
        else:
            self._archivos_ocupados.discard(clave)

        hubo_cambio_en_conjunto = self._archivos_ocupados != antes
        nueva_bloqueada = len(self._archivos_ocupados) > 0
        cambio_bloqueo = nueva_bloqueada != self._bloqueada
        self._bloqueada = nueva_bloqueada

        # Orden deliberado: primero se actualiza _bloqueada (arriba) y se
        # emite el detalle del conjunto, y solo despues el booleano
        # agregado -- asi, quien escuche archivos_ocupados_cambiado y
        # consulte esta_bloqueada() en el mismo instante ve siempre el
        # valor ya vigente, nunca el anterior.
        if hubo_cambio_en_conjunto:
            self.archivos_ocupados_cambiado.emit()
        if cambio_bloqueo:
            self.estado_app_cambiado.emit(self._bloqueada)

    def esta_bloqueada(self):
        return self._bloqueada

    def archivos_ocupados(self):
        return set(self._archivos_ocupados)
