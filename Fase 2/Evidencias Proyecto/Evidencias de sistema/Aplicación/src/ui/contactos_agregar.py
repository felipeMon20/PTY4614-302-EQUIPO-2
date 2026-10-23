import math
import os
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox,
                             QFrame, QApplication)
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve,
                          QRegularExpression, QRectF, QPointF)
from PyQt6.QtGui import (QRegularExpressionValidator, QPixmap, QPainter, QColor, QIcon,
                         QPolygonF, QPen)
import qtawesome as qta
from config.settings import POWERBI_EXCEL_PATH
from src.services import contactos_service, powerbi_cache_service
from src.theme.theme_manager import ThemeManager
from src.theme.colors import BACKGROUND, SURFACE, BORDER, PRIMARY, DANGER, SUCCESS, TEXT_PRIMARY, TEXT_SECONDARY


# Banderas simplificadas por ISO: franjas ('h' horizontales, 'v' verticales)
_FRANJAS = {
    'AR': ('h', ['#74ACDF', '#FFFFFF', '#74ACDF']),
    'PE': ('v', ['#D91023', '#FFFFFF', '#D91023']),
    'BO': ('h', ['#D52B1E', '#F9E300', '#007934']),
    'CO': ('h', ['#FCD116', '#FCD116', '#003893', '#CE1126']),
    'EC': ('h', ['#FFDD00', '#FFDD00', '#034EA2', '#ED1C24']),
    'MX': ('v', ['#006847', '#FFFFFF', '#CE1126']),
    'ES': ('h', ['#AA151B', '#F1BF00', '#F1BF00', '#AA151B']),
    'PY': ('h', ['#D52B1E', '#FFFFFF', '#0038A8']),
    'VE': ('h', ['#FFCC00', '#00247D', '#CF142B']),
    'DE': ('h', ['#000000', '#DD0000', '#FFCE00']),
    'FR': ('v', ['#0055A4', '#FFFFFF', '#EF4135']),
    'IT': ('v', ['#009246', '#FFFFFF', '#CE2B37']),
    'UY': ('h', ['#FFFFFF', '#0038A8'] * 4 + ['#FFFFFF']),
    'US': ('h', ['#B22234', '#FFFFFF'] * 3 + ['#B22234']),
}


def _estrella(centro, radio):
    puntos = []
    for i in range(10):
        r = radio if i % 2 == 0 else radio * 0.4
        ang = -90 + i * 36
        puntos.append(QPointF(centro.x() + r * math.cos(math.radians(ang)),
                              centro.y() + r * math.sin(math.radians(ang))))
    return QPolygonF(puntos)


def pixmap_bandera(iso, ancho=22, alto=15):
    """Dibuja una bandera simplificada; None si el país no tiene dibujo."""
    if iso not in _FRANJAS and iso not in ('CL', 'BR', 'SE', 'CN', 'GB'):
        return None
    escala = 3
    pm = QPixmap(ancho * escala, alto * escala)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(escala, escala)
    r = QRectF(0, 0, ancho, alto)
    p.setPen(Qt.PenStyle.NoPen)
    if iso in _FRANJAS:
        sentido, colores = _FRANJAS[iso]
        n = len(colores)
        for i, c in enumerate(colores):
            p.setBrush(QColor(c))
            if sentido == 'h':
                p.drawRect(QRectF(0, alto * i / n, ancho, alto / n + 0.5))
            else:
                p.drawRect(QRectF(ancho * i / n, 0, ancho / n + 0.5, alto))
        if iso == 'US':
            p.setBrush(QColor('#3C3B6E'))
            p.drawRect(QRectF(0, 0, ancho * 0.45, alto * 4 / 7))
        elif iso == 'UY':
            p.setBrush(QColor('#FFFFFF'))
            p.drawRect(QRectF(0, 0, ancho * 0.4, alto * 5 / 9))
            p.setBrush(QColor('#FCD116'))
            p.drawEllipse(QPointF(ancho * 0.2, alto * 0.28), alto * 0.15, alto * 0.15)
        elif iso == 'AR':
            p.setBrush(QColor('#F6B40E'))
            p.drawEllipse(r.center(), alto * 0.12, alto * 0.12)
    elif iso == 'CL':
        p.setBrush(QColor('#FFFFFF'))
        p.drawRect(QRectF(0, 0, ancho, alto / 2))
        p.setBrush(QColor('#D52B1E'))
        p.drawRect(QRectF(0, alto / 2, ancho, alto / 2))
        p.setBrush(QColor('#0039A6'))
        p.drawRect(QRectF(0, 0, alto / 2, alto / 2))
        p.setBrush(QColor('#FFFFFF'))
        p.drawPolygon(_estrella(QPointF(alto / 4, alto / 4), alto * 0.16))
    elif iso == 'BR':
        p.setBrush(QColor('#009C3B'))
        p.drawRect(r)
        p.setBrush(QColor('#FFDF00'))
        p.drawPolygon(QPolygonF([QPointF(ancho / 2, 1.5), QPointF(ancho - 2, alto / 2),
                                 QPointF(ancho / 2, alto - 1.5), QPointF(2, alto / 2)]))
        p.setBrush(QColor('#002776'))
        p.drawEllipse(r.center(), alto * 0.22, alto * 0.22)
    elif iso == 'SE':
        p.setBrush(QColor('#006AA7'))
        p.drawRect(r)
        p.setBrush(QColor('#FECC00'))
        p.drawRect(QRectF(ancho * 0.3, 0, alto * 0.2, alto))
        p.drawRect(QRectF(0, alto * 0.4, ancho, alto * 0.2))
    elif iso == 'CN':
        p.setBrush(QColor('#DE2910'))
        p.drawRect(r)
        p.setBrush(QColor('#FFDE00'))
        p.drawPolygon(_estrella(QPointF(alto * 0.33, alto * 0.33), alto * 0.2))
    elif iso == 'GB':
        p.setBrush(QColor('#012169'))
        p.drawRect(r)
        p.setPen(QPen(QColor('#FFFFFF'), alto * 0.2))
        p.drawLine(QPointF(0, 0), QPointF(ancho, alto))
        p.drawLine(QPointF(0, alto), QPointF(ancho, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#FFFFFF'))
        p.drawRect(QRectF(ancho / 2 - alto * 0.17, 0, alto * 0.34, alto))
        p.drawRect(QRectF(0, alto / 2 - alto * 0.17, ancho, alto * 0.34))
        p.setBrush(QColor('#C8102E'))
        p.drawRect(QRectF(ancho / 2 - alto * 0.1, 0, alto * 0.2, alto))
        p.drawRect(QRectF(0, alto / 2 - alto * 0.1, ancho, alto * 0.2))
    # Borde fino para que el blanco no se pierda con el fondo
    p.setPen(QPen(QColor(0, 0, 0, 50), 0.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r.adjusted(0.3, 0.3, -0.3, -0.3), 1.5, 1.5)
    p.end()
    pm.setDevicePixelRatio(escala)
    return pm


class PowerBiFlotasLoaderThread(QThread):
    """Lee POWERBI_EXCEL_PATH en un hilo secundario para no bloquear la UI al
    abrir ContactosAddDialog (antes: pd.read_excel sincrono en __init__,
    confirmado como bloqueo de 1-3s en docs/03 y docs/06). Misma logica
    exacta que tenia ContactosAddDialog._load_flotas_dict()."""
    loaded_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def run(self):
        dict_flotas = {}
        try:
            if POWERBI_EXCEL_PATH and os.path.exists(POWERBI_EXCEL_PATH):
                df_bbdd = powerbi_cache_service.leer_bbdd_clientes_cm(POWERBI_EXCEL_PATH)
                if 'CDB' in df_bbdd.columns and 'Nombre' in df_bbdd.columns:
                    df_bbdd = df_bbdd[['CDB', 'Nombre']]
                df_bbdd = df_bbdd.dropna(subset=['CDB'])
                df_bbdd['CDB_CLEAN'] = df_bbdd['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                dict_flotas = dict(zip(df_bbdd['CDB_CLEAN'], df_bbdd['Nombre'].astype(str).str.strip()))
        except Exception as e:
            self.error_signal.emit(str(e))
            return
        self.loaded_signal.emit(dict_flotas)

class VerificarDominioThread(QThread):
    """Consulta DNS del dominio del correo sin congelar el formulario."""
    resultado_signal = pyqtSignal(str, str)  # (correo, resultado)

    def __init__(self, correo, parent=None):
        super().__init__(parent)
        self.correo = correo

    def run(self):
        self.resultado_signal.emit(self.correo, contactos_service.verificar_dominio_correo(self.correo))


class ContactosAddDialog(QDialog):
    """`embebido=True` (05-10-2026): el formulario se incrusta en un panel
    lateral (Operaciones > Contactos) en vez de abrirse como ventana: sin
    encabezado, campos en una sola columna y ancho libre."""

    def __init__(self, parent=None, cdb_prefill=None, flota_prefill=None, embebido=False):
        super().__init__(parent)
        self.embebido = embebido
        self.setWindowTitle(" Agregar Nuevo Contacto de Flota")
        if not embebido:
            self.setFixedWidth(540)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {'transparent' if embebido else BACKGROUND}; }}
            QLabel {{ background: transparent; border: none; font-family: 'Segoe UI'; }}
            QLabel[rol="campo"] {{ color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold; }}
            QLabel[rol="seccion"] {{ color: {PRIMARY}; font-size: 10px; font-weight: bold; letter-spacing: 1px; }}
            QLineEdit {{ padding: {'5px' if embebido else '8px'} 10px; border: 1px solid #D1D5DB; border-radius: 8px;
                         background-color: {SURFACE}; color: {TEXT_PRIMARY}; font-size: 12px; }}
            QLineEdit:hover {{ border: 1px solid #9CA3AF; }}
            QLineEdit:focus {{ border: 1px solid {PRIMARY}; }}
            QLineEdit:read-only {{ background-color: #F1F5F9; color: #64748B; }}
            QLineEdit:disabled {{ background-color: #F1F5F9; color: #94A3B8; }}
            QLineEdit[error="true"] {{ border: 1px solid {DANGER}; background-color: #FEF2F2; }}
        """)

        self.inputs = {}
        self.dict_flotas = {}
        self.cdb_prefill = cdb_prefill
        self.flota_prefill = flota_prefill

        self._setup_ui()
        self._apply_prefill()
        # Cargamos el diccionario de Power BI en un QThread para no bloquear
        # la UI al abrir el dialogo (ver docstring de PowerBiFlotasLoaderThread).
        self._load_flotas_dict()

        self._anim_entrada = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_entrada.setDuration(160)
        self._anim_entrada.setStartValue(0.0)
        self._anim_entrada.setEndValue(1.0)
        self._anim_entrada.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.embebido:
            self._anim_entrada.start()

    def _load_flotas_dict(self):
        """Dispara la carga asincrona de Power BI. Mientras no termine, el
        campo CDB queda deshabilitado (salvo que ya venga precargado y
        bloqueado desde otro modulo, ej. MailDialog) para que el usuario no
        escriba un CDB contra un diccionario todavia vacio."""
        if self.cdb_prefill is None:
            self.inputs['CDB'].setEnabled(False)
            self.inputs['CDB'].setPlaceholderText("Cargando datos de Power BI...")

        self._flotas_thread = PowerBiFlotasLoaderThread()
        self._flotas_thread.loaded_signal.connect(self._on_flotas_loaded)
        self._flotas_thread.error_signal.connect(self._on_flotas_load_error)
        self._flotas_thread.start()

    def _on_flotas_loaded(self, dict_flotas):
        self.dict_flotas = dict_flotas
        self._unlock_cdb_field()
        # Si el CDB no viene precargado/bloqueado desde otro modulo, el
        # usuario pudo haber empezado a escribir mientras el diccionario
        # todavia estaba vacio: reevaluamos el autocompletado con el CDB
        # actual ahora que dict_flotas ya esta listo. Si viene precargado
        # (MailDialog), Flota ya quedo fijada por _apply_prefill y no debe
        # tocarse de nuevo aqui.
        if self.flota_prefill is None:
            self._on_cdb_changed(self.inputs['CDB'].text())

    def _on_flotas_load_error(self, error_msg):
        print(f"Aviso: No se pudo precargar Power BI para autocompletado - {error_msg}")
        self._unlock_cdb_field()

    def _unlock_cdb_field(self):
        if self.cdb_prefill is None:
            self.inputs['CDB'].setEnabled(True)
            self.inputs['CDB'].setPlaceholderText("Escribe el CDB...")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        self._acciones = {}

        if self.embebido:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

        # Encabezado: icono + título + subtítulo
        header = QHBoxLayout()
        header.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(52, 52)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(qta.icon('fa5s.user-plus', color=PRIMARY).pixmap(QSize(22, 22)))
        icono.setStyleSheet("background-color: #EFF6FF; border-radius: 26px;")
        header.addWidget(icono)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel("Nuevo contacto de flota")
        titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold;")
        subtitulo = QLabel("Se agregará como administrador de flota en el directorio de Contactos.")
        subtitulo.setWordWrap(True)
        subtitulo.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        textos.addWidget(titulo)
        textos.addWidget(subtitulo)
        header.addLayout(textos, 1)
        if not self.embebido:
            layout.addLayout(header)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta_contacto")
        tarjeta.setStyleSheet(f"QFrame#tarjeta_contacto {{ background-color: {SURFACE}; border-radius: 14px; border: 1px solid {BORDER}; }}")
        grid = QGridLayout(tarjeta)
        grid.setContentsMargins(*((16, 10, 16, 12) if self.embebido else (22, 18, 22, 22)))
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3 if self.embebido else 6)

        def crear_campo(nombre, icono_nombre, placeholder="", solo_lectura=False):
            w = QLineEdit()
            self._acciones[nombre] = w.addAction(qta.icon(icono_nombre, color='#94A3B8'), QLineEdit.ActionPosition.LeadingPosition)
            if placeholder:
                w.setPlaceholderText(placeholder)
            if solo_lectura:
                w.setReadOnly(True)
            w.textChanged.connect(lambda _t, w=w: self._marcar_error(w, False))
            self.inputs[nombre] = w
            return w

        def etiqueta(texto, rol="campo"):
            lbl = QLabel(texto)
            lbl.setProperty("rol", rol)
            return lbl

        fila = 0
        def seccion(texto):
            nonlocal fila
            lbl = etiqueta(texto, "seccion")
            if fila > 0:
                lbl.setContentsMargins(0, 6 if self.embebido else 12, 0, 0)
            grid.addWidget(lbl, fila, 0, 1, 2)
            fila += 1

        def par(izq, der=None):
            # Cada campo: etiqueta arriba, input abajo; der=None ocupa el ancho completo
            nonlocal fila
            if self.embebido:
                for nombre, widget in [izq] + ([der] if der else []):
                    grid.addWidget(etiqueta(nombre), fila, 0, 1, 2)
                    grid.addWidget(widget, fila + 1, 0, 1, 2)
                    fila += 2
                return
            for col, campo in enumerate([izq] + ([der] if der else [])):
                nombre, widget = campo
                span = 1 if der else 2
                grid.addWidget(etiqueta(nombre), fila, col, 1, span)
                grid.addWidget(widget, fila + 1, col, 1, span)
            fila += 2

        seccion("EMPRESA")
        par(("CDB *", crear_campo('CDB', 'fa5s.hashtag', "Escribe el CDB...")),
            ("Flota *", crear_campo('Flota', 'fa5s.building', "Se rellena sola si el CDB existe")))
        seccion("CONTACTO")
        par(("Nombre", crear_campo('Nombre', 'fa5s.user')),
            ("Apellidos", crear_campo('Apellidos', 'fa5s.user')))
        par(("Correo electrónico", crear_campo('Correo electrónico', 'fa5s.envelope', "nombre@empresa.cl")))
        self.lbl_correo = QLabel()
        self.lbl_correo.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        self.lbl_correo.hide()
        grid.addWidget(self.lbl_correo, fila, 0, 1, 2)
        fila += 1
        self._resultado_dominio = {}
        self._hilos_dominio = []
        self.inputs['Correo electrónico'].editingFinished.connect(self._verificar_dominio_async)
        self.inputs['Correo electrónico'].textChanged.connect(lambda _t: self.lbl_correo.hide())
        rol = crear_campo('Rol', 'fa5s.id-badge', solo_lectura=True)
        rol.setText("Administrador de flota")
        par(("Número móvil", crear_campo('Número móvil', 'fa5s.mobile-alt', "+56 9 1234 5678 (opcional)")),
            ("Rol", rol))
        self.lbl_pais = QLabel()
        self.lbl_pais.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        grid.addWidget(self.lbl_pais, fila, 0, 1, 2)
        fila += 1

        # Filtros mientras se escribe: letras en nombres, + y dígitos en el móvil
        solo_letras = QRegularExpressionValidator(QRegularExpression(r"^[\p{L} '´’\-]*$"), self)
        self.inputs['Nombre'].setValidator(solo_letras)
        self.inputs['Apellidos'].setValidator(solo_letras)
        telefono = self.inputs['Número móvil']
        telefono.setMaxLength(20)
        telefono.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\+?[0-9 ]*$"), self))
        telefono.textEdited.connect(self._forzar_mas_inicial)
        telefono.textChanged.connect(self._actualizar_pais)
        self._actualizar_pais("")
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Conectamos el evento "mientras el usuario escribe" a la función mágica
        self.inputs['CDB'].textChanged.connect(self._on_cdb_changed)

        layout.addWidget(tarjeta)

        btn_layout = QHBoxLayout()
        nota = QLabel("* Campos obligatorios")
        nota.setStyleSheet("color: #94A3B8; font-size: 11px;")
        if not self.embebido:
            btn_layout.addWidget(nota)
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setMinimumWidth(90 if self.embebido else 110)
        ThemeManager.apply_secondary_button(btn_cancel)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(" Guardar contacto")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setMinimumWidth(130 if self.embebido else 150)
        btn_save.setStyleSheet(
            "QPushButton { background-color: #1B2B4E; color: white; border: 1px solid #1B2B4E; border-radius: 9px; "
            "padding: 8px 16px; font-weight: 700; font-size: 12px; } "
            "QPushButton:hover { background-color: #2A3F6E; border-color: #2A3F6E; }")
        btn_save.setIcon(qta.icon('fa5s.save', color='white'))
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._validate_and_accept)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def _forzar_mas_inicial(self, texto):
        if texto and not texto.startswith('+'):
            campo = self.inputs['Número móvil']
            pos = campo.cursorPosition()
            campo.setText('+' + texto.replace('+', ''))
            campo.setCursorPosition(pos + 1)

    def _actualizar_pais(self, texto):
        """Bandera en el campo y país/ayuda debajo, según el código tipeado."""
        accion = self._acciones.get('Número móvil')
        digitos = ''.join(c for c in texto if c.isdigit())
        pais = contactos_service.detectar_pais_telefono(digitos) if texto.startswith('+') else None
        bandera = pixmap_bandera(pais[1]) if pais else None
        if accion is not None:
            accion.setIcon(QIcon(bandera) if bandera else qta.icon(
                'fa5s.globe-americas' if digitos else 'fa5s.mobile-alt', color='#94A3B8'))
        if not digitos:
            self.lbl_pais.setText("Opcional. Comienza con + y el código de país.")
            return
        valido, mensaje = contactos_service.validar_telefono(texto)
        if pais:
            codigo, _iso, nombre, minimo, maximo = pais
            largo = len(digitos) - len(codigo)
            esperado = minimo if largo < minimo else maximo
            estado = "✓" if valido else f"{largo}/{esperado} dígitos"
            self.lbl_pais.setText(f"{nombre} (+{codigo}) · {estado}")
        else:
            self.lbl_pais.setText("Código de país no reconocido" + ("" if valido else f" · {len(digitos)} dígitos"))

    def _verificar_dominio_async(self):
        correo = self.inputs['Correo electrónico'].text().strip()
        if not correo or not contactos_service.validar_correo(correo):
            return
        if correo in self._resultado_dominio:
            self._mostrar_resultado_dominio(correo, self._resultado_dominio[correo])
            return
        self._pintar_lbl_correo("Verificando dominio…", TEXT_SECONDARY)
        hilo = VerificarDominioThread(correo, self)
        hilo.resultado_signal.connect(self._mostrar_resultado_dominio)
        hilo.finished.connect(lambda h=hilo: self._hilos_dominio.remove(h) if h in self._hilos_dominio else None)
        self._hilos_dominio.append(hilo)
        hilo.start()

    def _mostrar_resultado_dominio(self, correo, resultado):
        self._resultado_dominio[correo] = resultado
        if correo != self.inputs['Correo electrónico'].text().strip():
            return
        dominio = correo.rsplit('@', 1)[1]
        if resultado == contactos_service.DOMINIO_OK:
            self._pintar_lbl_correo(f"✓ {dominio} recibe correo", SUCCESS)
        elif resultado == contactos_service.DOMINIO_NO_EXISTE:
            self._pintar_lbl_correo(f"✗ El dominio {dominio} no existe", DANGER)
            self._marcar_error(self.inputs['Correo electrónico'], True)
        elif resultado == contactos_service.DOMINIO_SIN_CORREO:
            self._pintar_lbl_correo(f"✗ {dominio} no está configurado para recibir correo", DANGER)
            self._marcar_error(self.inputs['Correo electrónico'], True)
        else:
            self._pintar_lbl_correo("No se pudo verificar el dominio (sin conexión). Se puede guardar igual.", TEXT_SECONDARY)

    def _pintar_lbl_correo(self, texto, color):
        self.lbl_correo.setText(texto)
        self.lbl_correo.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.lbl_correo.show()

    def done(self, r):
        for hilo in list(self._hilos_dominio):
            hilo.wait(5000)
        super().done(r)

    def _marcar_error(self, widget, error):
        if bool(widget.property("error")) == error:
            return
        widget.setProperty("error", error)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _apply_prefill(self):
        """Cuando el diálogo se abre desde otro módulo (ej. Correos) con un CDB
        y una Flota ya conocidos, los precarga y los bloquea para que el
        usuario no pueda cambiarlos por error. El resto de los campos
        permanece editable como siempre."""
        if self.cdb_prefill is not None:
            self.inputs['CDB'].setText(str(self.cdb_prefill))
            self.inputs['CDB'].setReadOnly(True)
        if self.flota_prefill is not None:
            # Se fija DESPUÉS del CDB para que gane sobre el autocompletado
            # de Power BI que _on_cdb_changed pudo haber disparado arriba.
            self.inputs['Flota'].setText(str(self.flota_prefill))
            self.inputs['Flota'].setReadOnly(True)

    def _on_cdb_changed(self, text):
        """Escucha cada tecla tipeada en CDB. Si detecta uno válido, autocompleta al instante."""
        cdb = text.strip()
        
        if cdb in self.dict_flotas:
            flota_nombre = self.dict_flotas[cdb]
            if flota_nombre and flota_nombre.lower() != 'nan':
                # Lo encuentra: Rellena y Bloquea
                self.inputs['Flota'].setText(flota_nombre)
                self.inputs['Flota'].setReadOnly(True)
            else:
                # Existe pero sin nombre: Desbloquea
                self.inputs['Flota'].setText("")
                self.inputs['Flota'].setReadOnly(False)
        else:
            # CDB nuevo o incompleto: Desbloquea para escritura manual
            self.inputs['Flota'].setText("")
            self.inputs['Flota'].setReadOnly(False)

    def _validate_and_accept(self):
        for campo, mensaje in (('CDB', "El CDB es obligatorio."), ('Flota', "El campo Flota es obligatorio.")):
            if not self.inputs[campo].text().strip():
                self._marcar_error(self.inputs[campo], True)
                self.inputs[campo].setFocus()
                QMessageBox.warning(self, "Campo Obligatorio", mensaje)
                return
            
        for campo in ('Nombre', 'Apellidos'):
            if not contactos_service.validar_nombre(self.inputs[campo].text()):
                self._rechazar(campo, f"{campo} solo puede contener letras (se aceptan acentos y ñ).")
                return
        if not contactos_service.validar_correo(self.inputs['Correo electrónico'].text()):
            self._rechazar('Correo electrónico', "El correo no tiene un formato válido (ej: nombre@empresa.cl).")
            return
        correo = self.inputs['Correo electrónico'].text().strip()
        if correo:
            resultado = self._resultado_dominio.get(correo)
            if resultado is None:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    resultado = contactos_service.verificar_dominio_correo(correo, timeout=3.0)
                finally:
                    QApplication.restoreOverrideCursor()
                self._mostrar_resultado_dominio(correo, resultado)
            if resultado in (contactos_service.DOMINIO_NO_EXISTE, contactos_service.DOMINIO_SIN_CORREO):
                dominio = correo.rsplit('@', 1)[1]
                self._rechazar('Correo electrónico', f'El dominio "{dominio}" no puede recibir correo. Revisa que esté bien escrito.')
                return

        # --- FORMATEO INTELIGENTE DE TELÉFONO ANTES DE GUARDAR ---
        phone_input = self.inputs['Número móvil']
        texto_tel = contactos_service.normalizar_telefono_ingresado(phone_input.text())
        valido, mensaje = contactos_service.validar_telefono(texto_tel)
        if not valido:
            self._rechazar('Número móvil', mensaje)
            return
        phone_input.setText(contactos_service.formatear_telefono_internacional(texto_tel))

        self.accept()

    def _rechazar(self, campo, mensaje):
        self._marcar_error(self.inputs[campo], True)
        self.inputs[campo].setFocus()
        QMessageBox.warning(self, "Dato inválido", mensaje)

    def get_data(self):
        data = {}
        for key, widget in self.inputs.items():
            data[key] = widget.text().strip()
                
        # --- INYECCIÓN DE FECHA CON HORA EXACTA ---
        data['Fecha de extracción'] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        return data