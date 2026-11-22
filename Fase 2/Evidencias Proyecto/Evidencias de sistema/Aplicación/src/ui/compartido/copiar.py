"""Copiar al portapapeles con aviso visible.

En Windows el portapapeles puede estar tomado un instante por otro programa (gestor de portapapeles,
escritorio remoto, Outlook) y Qt falla sin avisar: antes el clic no hacía nada visible y había que repetirlo.
Aquí se verifica lo copiado, se reintenta unas veces y la etiqueta muestra "Copiado" o el fallo."""
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

INTENTOS = 8
ESPERA_ENTRE_INTENTOS_S = 0.04
DURACION_AVISO_MS = 1100
TEXTO_OK = "✓ Copiado"
TEXTO_ERROR = "No se pudo copiar"
_COLOR_OK = "#0F9D6E"
_COLOR_ERROR = "#C0392B"
_VACIOS = ("", "—", "-")


def _normalizado(texto):
    return str(texto).replace("\r\n", "\n").strip()


def escribir_portapapeles(texto):
    """Copia `texto` y lo verifica leyendo el portapapeles; reintenta si otro programa lo tenía tomado.
    Devuelve True si quedó copiado."""
    portapapeles = QApplication.clipboard()
    esperado = _normalizado(texto)
    for intento in range(INTENTOS):
        try:
            portapapeles.setText(str(texto))
            if _normalizado(portapapeles.text()) == esperado:
                return True
        except RuntimeError:
            pass
        if intento < INTENTOS - 1:
            time.sleep(ESPERA_ENTRE_INTENTOS_S)
    return False


def _restaurar(etiqueta, generacion):
    try:
        estado = etiqueta.__dict__.get('_copia_estado')
        if estado is None or estado['generacion'] != generacion:
            return
        # Si la ficha cambió el texto mientras tanto, no se pisa
        if etiqueta.text() == estado['aviso']:
            etiqueta.setText(estado['texto'])
        etiqueta.setStyleSheet(estado['estilo'])
        etiqueta.__dict__.pop('_copia_estado', None)
    except RuntimeError:
        pass  # la etiqueta se destruyó


def _avisar(etiqueta, ok):
    """Cambia un momento el texto de la etiqueta a "Copiado" (o al error) y luego lo devuelve."""
    try:
        estado = etiqueta.__dict__.get('_copia_estado')
        if estado is None:
            estado = {'texto': etiqueta.text(), 'estilo': etiqueta.styleSheet(), 'generacion': 0}
            etiqueta.__dict__['_copia_estado'] = estado
        estado['generacion'] += 1
        estado['aviso'] = TEXTO_OK if ok else TEXTO_ERROR
        etiqueta.setText(estado['aviso'])
        color = _COLOR_OK if ok else _COLOR_ERROR
        etiqueta.setStyleSheet(estado['estilo'] + f"; color: {color}; font-weight: bold;")
        generacion = estado['generacion']
        QTimer.singleShot(DURACION_AVISO_MS, lambda: _restaurar(etiqueta, generacion))
    except RuntimeError:
        pass


def copiar_texto(texto, etiqueta=None):
    """Copia `texto` y, si se entrega `etiqueta`, avisa "Copiado" (o el fallo) en ella."""
    ok = escribir_portapapeles(texto)
    if etiqueta is not None:
        _avisar(etiqueta, ok)
    return ok


def texto_de_etiqueta(etiqueta):
    """Texto real de la etiqueta, aunque en este momento esté mostrando el aviso "Copiado"."""
    estado = etiqueta.__dict__.get('_copia_estado')
    return estado['texto'] if estado is not None else etiqueta.text()


def copiar_etiqueta(etiqueta):
    """Copia el texto de la etiqueta (ignora los vacíos "—" y "-") y avisa en la misma etiqueta."""
    texto = texto_de_etiqueta(etiqueta).strip()
    if texto in _VACIOS:
        return False
    ok = escribir_portapapeles(texto)
    _avisar(etiqueta, ok)
    return ok


def hacer_copiable(etiqueta, *tambien_clic, accion=None):
    """Un clic en la etiqueta, y en los widgets de `tambien_clic` (el prefijo y el ícono de copiar de la fila),
    copia el valor de la etiqueta y lo avisa. Con `accion` se ejecuta eso en vez de copiar el texto de la
    etiqueta (para pantallas que copian otro dato)."""
    def al_presionar(evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            if accion is not None:
                accion()
            else:
                copiar_etiqueta(etiqueta)

    for widget in (etiqueta, *tambien_clic):
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setToolTip("Clic para copiar")
        widget.mousePressEvent = al_presionar
