import html
import logging
import os
import time
import sys
import shutil
from datetime import datetime
import openpyxl
import qtawesome as qta
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QFileDialog, QMessageBox, 
                             QFrame, QGridLayout, QScrollArea, QDialog, QTextEdit, QApplication, QStackedWidget,
                             QAbstractButton, QSizePolicy, QButtonGroup)
from urllib.parse import urlparse
from PyQt6.QtCore import Qt, QSize, QProcess, QPointF, QRectF, pyqtSignal, QVariantAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTransform
from config.settings import load_config, save_config, EXCEL_PATH
from config import rutas
from config import settings as ajustes
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.registro_app import RUTA_LOG
from src.services.demo_service import restaurar_datos_demostracion
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
from src.theme.ui_scale import NIVELES_ESCALA, get_nivel_escala, set_nivel_escala
from src.theme import menu_fotos
from src.ui.administracion import estilo as admin_estilo
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.esqueleto_carga import animar_caja
from src.ui.ayuda.guia_conexion import GuiaConexionDialog
from src.ui.ayuda.ayuda_botones import crear_pagina_ayuda
from src.theme.tema import GestorTema, CLARO, OSCURO

logger = logging.getLogger(__name__)

VOLVO = "#003057"
VOLVO_HOVER = "#00446F"
VOLVO_SUAVE = "#E4EDF6"
_SIN_FONDO = "border: none; background: transparent;"


class _InterruptorDatos(QAbstractButton):
    """Interruptor encendido/apagado: verde con datos falsos, rojo con datos reales."""

    def __init__(self, marcado=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(marcado)
        self.setFixedSize(52, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SUCCESS if self.isChecked() else "#94A3B8"))
        p.drawRoundedRect(self.rect(), 15, 15)
        p.setBrush(QColor("white"))
        p.drawEllipse(25 if self.isChecked() else 3, 3, 24, 24)
        p.end()


class _OpcionCompacta(QFrame):
    """Opción seleccionable de Apariencia: vista pequeña a la izquierda, título y detalle a la derecha."""
    clicked = pyqtSignal()

    def __init__(self, vista, titulo, detalle, parent=None):
        super().__init__(parent)
        self.setObjectName("opcionCompacta")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 14, 10)
        lay.setSpacing(12)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        lbl_detalle = QLabel(detalle)
        lbl_detalle.setStyleSheet(f"font-size: 11.5px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        textos.addWidget(lbl_titulo)
        textos.addWidget(lbl_detalle)
        lay.addWidget(vista)
        lay.addLayout(textos, 1)
        for hijo in (vista, lbl_titulo, lbl_detalle):
            hijo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.marcar(False)

    def marcar(self, activa):
        borde = f"1.5px solid {VOLVO}" if activa else f"1px solid {estilo_com.LINEA}"
        fondo = VOLVO_SUAVE if activa else estilo_com.SUPERFICIE
        self.setStyleSheet(f"QFrame#opcionCompacta {{ background: {fondo}; border: {borde}; border-radius: 12px; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _MiniTema(QWidget):
    """Vista previa del tema: ventana con barra lateral y tres rayas."""

    def __init__(self, oscuro, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 34)
        self._colores = (("#16202E", "#0B1A2B", "#33465F", "#5AA2DC") if oscuro
                         else ("#F5F7FA", VOLVO, "#D3DBE6", VOLVO))

    def paintEvent(self, _evento):
        fondo, barra, linea, acento = self._colores
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = QPainterPath()
        marco.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 7, 7)
        p.setClipPath(marco)
        p.fillRect(self.rect(), QColor(fondo))
        p.fillRect(0, 0, 12, self.height(), QColor(barra))
        p.setPen(Qt.PenStyle.NoPen)
        for i, (ancho, color) in enumerate(((20, acento), (28, linea), (24, linea))):
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(18, 7 + i * 7, ancho, 3), 1.5, 1.5)
        p.setClipping(False)
        p.setPen(QColor(estilo_com.LINEA))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 7, 7)
        p.end()


class _MiniTamano(QLabel):
    """Vista previa del tamaño: un "Aa" con el cuerpo de letra del nivel."""

    def __init__(self, punto, parent=None):
        super().__init__("Aa", parent)
        self.setFixedSize(46, 34)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 7px; "
                           f"font-size: {punto}px; font-weight: 700; color: {estilo_com.TINTA};")


class _MiniaturaFoto(QWidget):
    """Foto del menú lateral como mosaico seleccionable: llena el ancho disponible, centrada en el camión, con el
    nombre abajo y una marca cuando está elegida. Con varias fotos las reparte en franjas verticales."""
    clicked = pyqtSignal()
    ALTO = 78
    RADIO = 10

    def __init__(self, carpeta_assets, ids, nombre, mezclar=False, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.ALTO)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fotos = [(QPixmap(menu_fotos.ruta_foto(carpeta_assets, i)), menu_fotos.FOCO_Y.get(i, 0.55)) for i in ids]
        self._nombre = nombre
        self._mezclar = mezclar
        self._activa = False

    def marcar(self, activa):
        self._activa = activa
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    @staticmethod
    def _origen(pm, foco, ancho, alto):
        """Zona de la foto que cubre un rectángulo ancho x alto, con el foco a la altura del camión."""
        if pm.isNull() or ancho <= 0 or alto <= 0:
            return QRectF()
        if ancho / alto > pm.width() / pm.height():
            h = pm.width() * alto / ancho
            y = min(max(pm.height() * foco - h / 2, 0), pm.height() - h)
            return QRectF(0, y, pm.width(), h)
        w = pm.height() * ancho / alto
        return QRectF((pm.width() - w) / 2, 0, w, pm.height())

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        marco = QPainterPath()
        marco.addRoundedRect(area, self.RADIO, self.RADIO)
        p.setClipPath(marco)
        p.fillRect(self.rect(), QColor("#0C2244"))
        n = len(self._fotos)
        for i, (pm, foco) in enumerate(self._fotos):
            x0, x1 = round(self.width() * i / n), round(self.width() * (i + 1) / n)
            destino = QRectF(x0, 0, x1 - x0, self.height())
            p.drawPixmap(destino, pm, self._origen(pm, foco, destino.width(), destino.height()))
            if i:
                p.fillRect(QRectF(x0 - 1, 0, 2, self.height()), QColor(255, 255, 255, 90))
        if self._mezclar:
            p.fillRect(self.rect(), QColor(8, 24, 51, 110))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            centro = QPointF(self.width() / 2, self.height() / 2 - 6)
            p.drawEllipse(centro, 15, 15)
            icono = qta.icon('fa5s.random', color=VOLVO).pixmap(QSize(16, 16))
            p.drawPixmap(round(centro.x() - 8), round(centro.y() - 8), icono)
        fundido = QLinearGradient(0, self.height() - 30, 0, self.height())
        fundido.setColorAt(0.0, QColor(5, 15, 32, 0))
        fundido.setColorAt(1.0, QColor(5, 15, 32, 215))
        p.fillRect(QRectF(0, self.height() - 30, self.width(), 30), fundido)
        fuente = p.font()
        fuente.setPixelSize(11)
        fuente.setBold(True)
        p.setFont(fuente)
        p.setPen(QColor("white"))
        texto = p.fontMetrics().elidedText(self._nombre, Qt.TextElideMode.ElideRight, self.width() - 16)
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, texto)
        p.setClipping(False)
        if self._activa:
            p.setPen(QPen(QColor(VOLVO), 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(area, self.RADIO, self.RADIO)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(VOLVO))
            marca = QRectF(self.width() - 25, 6, 18, 18)
            p.drawEllipse(marca)
            p.setPen(QColor("white"))
            fuente.setPixelSize(12)
            p.setFont(fuente)
            p.drawText(marca, Qt.AlignmentFlag.AlignCenter, "✓")
        p.end()

class ConfiguracionModule(QWidget):
    _CLAVES_RUTAS = ("EXCEL_PATH", "PROVISION_EXCEL_PATH", "POWERBI_EXCEL_PATH", "CONTACTOS_EXCEL_PATH",
                     "INSTALACIONES_PATH", "CORREOS_EXCEL_PATH", "LOG_CSV_PATH", "DELETED_LOG_EXCEL_PATH",
                     "CASOS_BAJA_CM_PATH", "EJECUTIVOS_PATH", "METAS_VC_PATH")

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.data_manager = DataManager()
        self.last_errors = []
        self.last_alerts = []
        
        self.path_inputs = {}
        self.url_inputs = {}
        # Rutas sin campo propio (ej. facturacionManual.xlsx) que la autodetección sí completa
        self._rutas_extra = {k: self.config.get(k, "") for k in ("FACTURACION_MANUAL_PATH",)}
        
        self.data_manager.data_ready.connect(self.update_health_panel)
        self._setup_ui()

    def _setup_ui(self):
        raiz = admin_estilo.raiz_pantalla(self)
        fila_cajas = QHBoxLayout()
        fila_cajas.setSpacing(12)
        raiz.addLayout(fila_cajas, 1)

        self.card_db = self._create_status_card("Base de datos", "fa5s.database", "#1B2B4E", "Cargando...")
        self.card_rows = self._create_status_card("Total contratos", "fa5s.truck", "#1B2B4E", "Cargando...")
        self.card_sync = self._create_status_card("Última modificación", "fa5s.clock", "#1B2B4E", "Cargando...")
        self.card_ram = self._create_status_card("Memoria RAM", "fa5s.microchip", "#1B2B4E", "Cargando...")
        self.card_load_time = self._create_status_card("Tiempo de lectura", "fa5s.tachometer-alt", "#1B2B4E", "Cargando...")
        self.card_logs = self._create_status_card("Estado de logs", "fa5s.heartbeat", "#1B2B4E", "Cargando...")
        # Visible solo cuando el registro tiene alertas o errores
        self.btn_ver_alertas = QPushButton("Ver")
        self.btn_ver_alertas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ver_alertas.setToolTip("Ver el detalle de las alertas y errores, y limpiar el registro")
        self.btn_ver_alertas.setStyleSheet(
            f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {VOLVO}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 8px; padding: 3px 12px; font-size: 11px; font-weight: 700; }"
            f"QPushButton:hover {{ border-color: {VOLVO}; }}")
        self.btn_ver_alertas.setVisible(False)
        self.btn_ver_alertas.clicked.connect(self._show_error_dialog)
        self.card_logs['frame'].layout().addWidget(self.btn_ver_alertas)

        # Caja izquierda: secciones y acciones
        izq = admin_estilo.caja_con_encabezado("cajaConfigSecciones", "Configuración", "Datos, enlaces y apariencia")
        izq.marco.setFixedWidth(250)
        cuerpo_izq = QVBoxLayout()
        cuerpo_izq.setContentsMargins(12, 12, 12, 12)
        cuerpo_izq.setSpacing(8)
        cuerpo_izq.addWidget(admin_estilo.etiqueta_caja("SECCIÓN"))
        self._grupo_secciones = QButtonGroup(self)
        self._grupo_secciones.setExclusive(True)
        self._botones_seccion, self._badges = [], []
        for i, (nombre, icono) in enumerate((("Archivos", "fa5s.folder-open"), ("Enlaces", "fa5s.link"),
                                              ("Apariencia", "fa5s.palette"), ("Modo Programador", "fa5s.tools"),
                                              ("Ayuda", "fa5s.question-circle"))):
            boton, badge = admin_estilo.boton_seccion(nombre, icono)
            badge.setVisible(i < 2)
            self._grupo_secciones.addButton(boton, i)
            self._botones_seccion.append(boton)
            self._badges.append(badge)
            cuerpo_izq.addWidget(boton)
        admin_estilo.fijar_badge(self._badges[1], len(self._ENLACES))
        self._botones_seccion[0].setChecked(True)
        cuerpo_izq.addStretch(1)
        cuerpo_izq.addWidget(admin_estilo.etiqueta_caja("ACCIONES"))
        self.btn_refresh = admin_estilo.boton_accion("Actualizar estado", 'fa5s.sync-alt')
        self.btn_refresh.clicked.connect(self.force_refresh)
        btn_save = admin_estilo.boton_accion("Guardar y reiniciar", 'fa5s.save')
        btn_save.clicked.connect(self._save_changes)
        self.btn_view_errors = admin_estilo.boton_accion("Ver alertas", 'fa5s.search', peligro=True)
        self.btn_view_errors.setVisible(False)
        self.btn_view_errors.clicked.connect(self._show_error_dialog)
        cuerpo_izq.addWidget(self.btn_view_errors)
        cuerpo_izq.addWidget(self.btn_refresh)
        cuerpo_izq.addWidget(btn_save)
        izq.cuerpo.addLayout(cuerpo_izq)
        fila_cajas.addWidget(izq.marco)

        # Caja central: la sección elegida
        centro = admin_estilo.caja_con_encabezado("cajaConfigContenido", "Archivos", "")
        self.lbl_cab_titulo, self.lbl_cab_sub = centro.lbl_titulo, centro.lbl_subtitulo
        self.lbl_cab_pastilla = QLabel("")
        self.lbl_cab_pastilla.setStyleSheet("background: rgba(255,255,255,0.16); color: white; border-radius: 10px; "
                                            "padding: 3px 11px; font-size: 11px; font-weight: 700; border: none;")
        centro.fila_cab.addWidget(self.lbl_cab_pastilla)
        self._pastillas = ["", "", "", "", ""]
        fila_cajas.addWidget(centro.marco, 1)
        self._caja_centro = centro.marco

        # Las rutas ya no se editan una a una: viven en campos que completa la carpeta de datos
        for config_key in self._CLAVES_RUTAS:
            self.path_inputs[config_key] = QLineEdit(self.config.get(config_key, ""))

        self.paginas = QStackedWidget()
        centro.cuerpo.addWidget(self.paginas, 1)

        # Caja derecha: estado del sistema, siempre a la vista
        der = admin_estilo.caja_con_encabezado("cajaConfigEstado", "Estado del sistema", "Siempre a la vista")
        der.marco.setFixedWidth(280)
        # De lo más importante a lo menos: salud del sistema, datos y, al final, actualizaciones
        contenido_der = QWidget()
        contenido_der.setStyleSheet("background: transparent;")
        cuerpo_der = QVBoxLayout(contenido_der)
        cuerpo_der.setContentsMargins(12, 12, 12, 12)
        cuerpo_der.setSpacing(10)
        cuerpo_der.addWidget(self._grupo_estado("fa5s.heartbeat", "Salud del sistema",
                                                (self.card_db, self.card_logs, self.card_load_time, self.card_ram)))
        cuerpo_der.addWidget(self._grupo_estado("fa5s.database", "Datos",
                                                (self.card_rows, self.card_sync)))
        cuerpo_der.addWidget(self._crear_bloque_actualizaciones())
        cuerpo_der.addStretch(1)
        area_der = QScrollArea()
        area_der.setWidgetResizable(True)
        area_der.setFrameShape(QFrame.Shape.NoFrame)
        area_der.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area_der.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        area_der.viewport().setAutoFillBackground(False)
        area_der.setWidget(contenido_der)
        der.cuerpo.addWidget(area_der, 1)
        fila_cajas.addWidget(der.marco)

        for pagina in (self._crear_grupo_carpeta_datos(), self._crear_pagina_enlaces(),
                       self._crear_grupo_escala(), self._crear_pagina_avanzado()):
            self._con_desplazamiento(pagina, self.paginas)
        # Ayuda es la página más grande (~600 widgets): se arma la primera vez que se abre.
        # Lleva su propio desplazamiento, así que no va dentro de otro
        self._area_ayuda = QWidget()
        self._area_ayuda.setObjectName("paginaConfiguracion")
        self._area_ayuda.setStyleSheet("QWidget#paginaConfiguracion { background: transparent; }")
        self._ayuda_armada = False
        self.paginas.addWidget(self._area_ayuda)
        self._grupo_secciones.idClicked.connect(self._cambiar_seccion)

        if not ajustes.MODO_PROGRAMADOR:
            self._botones_seccion[3].setVisible(False)
        for txt in self.path_inputs.values():
            txt.textChanged.connect(lambda *_: self._refrescar_estado_rutas())
        self._refrescar_estado_rutas()
        self._cambiar_seccion(0)
        self.update_health_panel()

    _TITULOS_SECCION = (("Archivos", "Carpeta de datos y estado de cada archivo"),
                        ("Enlaces", "Direcciones web que usa la aplicación"),
                        ("Apariencia", "Tema, tamaño de la interfaz y foto del menú"),
                        ("Modo Programador", "Herramientas de programador"),
                        ("Ayuda", "Qué hace cada botón y cuándo se usa"))

    def _cambiar_seccion(self, indice):
        cambia = indice != self.paginas.currentIndex()
        self._asegurar_pagina_ayuda(indice)
        self.paginas.setCurrentIndex(indice)
        if cambia:
            animar_caja(self._caja_centro)
        titulo, sub = self._TITULOS_SECCION[indice]
        self.lbl_cab_titulo.setText(titulo)
        self.lbl_cab_sub.setText(sub)
        self._mostrar_pastilla(indice)

    def _mostrar_pastilla(self, indice):
        if indice == self.paginas.currentIndex():
            texto = self._pastillas[indice]
            self.lbl_cab_pastilla.setText(texto)
            self.lbl_cab_pastilla.setVisible(bool(texto))

    @staticmethod
    def _pagina():
        pagina = QWidget()
        pagina.setObjectName("paginaConfiguracion")
        pagina.setStyleSheet("QWidget#paginaConfiguracion { background: transparent; }")
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        return pagina, lay

    @staticmethod
    def _con_desplazamiento(pagina, pila):
        """Cada pestaña mantiene su altura natural y se desplaza si no cabe."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        area.viewport().setAutoFillBackground(False)
        pila.addWidget(area)
        if pagina is not None:
            area.setWidget(pagina)
        return area

    def _asegurar_pagina_ayuda(self, indice):
        if self.paginas.widget(indice) is self._area_ayuda and not self._ayuda_armada:
            self._ayuda_armada = True
            lay = QVBoxLayout(self._area_ayuda)
            lay.setContentsMargins(20, 14, 20, 0)
            lay.setSpacing(0)
            lay.addWidget(crear_pagina_ayuda(self._titulo_pagina))

    @staticmethod
    def _encabezado_grupo(icono, titulo):
        """Fila de cabecera de las tarjetas de la caja derecha: ícono en cuadro azul y título."""
        cab = QHBoxLayout()
        cab.setSpacing(9)
        insignia = QLabel()
        insignia.setFixedSize(28, 28)
        insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        insignia.setPixmap(qta.icon(icono, color='white').pixmap(QSize(13, 13)))
        insignia.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1B2B4E, stop:1 #2C4A80); "
                               "border-radius: 9px; border: none;")
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 13px; font-weight: 800; {_SIN_FONDO}")
        lbl_titulo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cab.addWidget(insignia)
        cab.addWidget(lbl_titulo, 1)
        return cab

    def _grupo_estado(self, icono, titulo, tarjetas):
        """Tarjeta de la caja derecha con una lista de datos del sistema, del mismo estilo que la de actualizaciones."""
        marco = QFrame()
        marco.setObjectName("grupoEstadoConfig")
        marco.setStyleSheet(f"QFrame#grupoEstadoConfig {{ background: {estilo_com.SUPERFICIE_2}; "
                            f"border: 1px solid {estilo_com.LINEA}; border-radius: 14px; }}")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(4)
        lay.addLayout(self._encabezado_grupo(icono, titulo))
        for n, tarjeta in enumerate(tarjetas):
            lay.addWidget(self._linea())
            tarjeta['frame'].setMinimumHeight(40)
            lay.addWidget(tarjeta['frame'])
        return marco

    def _crear_bloque_actualizaciones(self):
        """Versión instalada y publicada, con los botones para buscar e instalar (caja Estado del sistema)."""
        from src.core.actualizador import ControlActualizacion
        self._control_act = ControlActualizacion.instancia()
        self._buscando = False
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaActualizaciones")
        tarjeta.setStyleSheet(f"QFrame#tarjetaActualizaciones {{ background: {estilo_com.SUPERFICIE_2}; "
                              f"border: 1px solid {estilo_com.LINEA}; border-radius: 14px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(9)

        cab = self._encabezado_grupo('fa5s.cloud-download-alt', "Actualizaciones")
        self.lbl_act_estado = QLabel("")
        cab.addWidget(self.lbl_act_estado)
        lay.addLayout(cab)

        fila_versiones = QHBoxLayout()
        fila_versiones.setSpacing(8)
        self.lbl_act_instalada = QLabel(self._control_act.version_instalada)
        self.lbl_act_publicada = QLabel("")
        for etiqueta, valor in (("Instalada", self.lbl_act_instalada), ("Publicada", self.lbl_act_publicada)):
            casilla = QFrame()
            casilla.setObjectName("casillaVersion")
            casilla.setStyleSheet(f"QFrame#casillaVersion {{ background: {estilo_com.SUPERFICIE}; "
                                  f"border: 1px solid {estilo_com.LINEA}; border-radius: 10px; }}")
            col = QVBoxLayout(casilla)
            col.setContentsMargins(10, 6, 10, 7)
            col.setSpacing(0)
            titulo = QLabel(etiqueta.upper())
            titulo.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 9px; font-weight: 800; letter-spacing: 1px; {_SIN_FONDO}")
            valor.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: 800; {_SIN_FONDO}")
            col.addWidget(titulo)
            col.addWidget(valor)
            casilla.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            fila_versiones.addWidget(casilla, 1)
        lay.addLayout(fila_versiones)

        self.lbl_act_notas = QLabel()
        self.lbl_act_notas.setWordWrap(True)
        self.lbl_act_notas.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lay.addWidget(self.lbl_act_notas)

        self.btn_act_instalar = admin_estilo.boton_accion("Actualizar ahora", 'fa5s.download')
        self.btn_act_instalar.clicked.connect(self._instalar_actualizacion)
        self.btn_act_buscar = admin_estilo.boton_accion("Buscar actualizaciones", 'fa5s.sync-alt')
        self.btn_act_buscar.clicked.connect(self._buscar_actualizaciones)
        for btn in (self.btn_act_instalar, self.btn_act_buscar):
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            lay.addWidget(btn)

        self.lbl_act_revision = QLabel()
        self.lbl_act_revision.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_act_revision.setStyleSheet(f"font-size: 10px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lbl_autor = QLabel("Gestor SSCC · Felipe Monsalve Umanzor")
        lbl_autor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_autor.setStyleSheet(f"font-size: 10px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        for lbl in (self.lbl_act_revision, lbl_autor):
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lay.addWidget(lbl)
        self._control_act.cambio.connect(self._refrescar_actualizaciones)
        self._refrescar_actualizaciones()
        return tarjeta

    def _buscar_actualizaciones(self):
        """Busca una versión nueva con el ícono girando hasta que termine la revisión."""
        if self._buscando:
            return
        self._buscando = True
        self._inicio_busqueda = time.monotonic()
        self.btn_act_buscar.setText("  Buscando...")
        icono = qta.icon('fa5s.sync-alt', color='white').pixmap(QSize(16, 16))
        giro = QVariantAnimation(self)
        giro.setStartValue(0.0)
        giro.setEndValue(360.0)
        giro.setDuration(800)
        giro.setLoopCount(-1)

        def _girar(grados):
            rotado = icono.transformed(QTransform().rotate(grados), Qt.TransformationMode.SmoothTransformation)
            self.btn_act_buscar.setIcon(QIcon(rotado.copy((rotado.width() - 16) // 2, (rotado.height() - 16) // 2, 16, 16)))

        giro.valueChanged.connect(_girar)
        giro.start()
        self._giro_busqueda = giro
        self._control_act.buscar()
        QTimer.singleShot(1000, self._terminar_busqueda)

    def _terminar_busqueda(self):
        if not self._buscando or self._control_act.revision_en_curso:
            return
        resto = 900 - int((time.monotonic() - self._inicio_busqueda) * 1000)
        if resto > 0:
            QTimer.singleShot(resto, self._terminar_busqueda)
            return
        self._giro_busqueda.stop()
        self._buscando = False
        self.btn_act_buscar.setIcon(qta.icon('fa5s.check', color='white'))
        self.btn_act_buscar.setText("  Revisado")

        def _restaurar():
            if not self._buscando:
                self.btn_act_buscar.setIcon(qta.icon('fa5s.sync-alt', color='white'))
                self.btn_act_buscar.setText("  Buscar actualizaciones")

        QTimer.singleShot(1300, _restaurar)

    def _refrescar_actualizaciones(self):
        from src.services.actualizador_service import puede_instalar
        control = self._control_act
        man = control.manifiesto
        disponible = control.disponible()
        if control.revision_en_curso:
            publicada, estado, fondo, color = "…", "Buscando", estilo_com.LINEA, estilo_com.APAGADO
        elif man is None:
            publicada, estado, fondo, color = "—", "Sin conexión", "#FDECEC", DANGER
        elif disponible:
            publicada, estado, fondo, color = man["version"], "Versión nueva", "#FEF3DC", "#B26B00"
        else:
            publicada, estado, fondo, color = man["version"], "Al día", "#E3F6EE", SUCCESS
        self.lbl_act_publicada.setText(publicada)
        self.lbl_act_estado.setText(estado)
        self.lbl_act_estado.setStyleSheet(f"background: {fondo}; color: {color}; font-size: 10px; font-weight: 800; "
                                          "border-radius: 9px; padding: 3px 9px; border: none;")
        self.lbl_act_estado.setToolTip("No se pudo leer la carpeta de actualizaciones" if man is None and not control.revision_en_curso else "")
        self.btn_act_instalar.setVisible(bool(disponible))
        self.lbl_act_notas.setText(man["notas"] if disponible and man["notas"] else "")
        self.lbl_act_notas.setVisible(bool(self.lbl_act_notas.text()))
        self.btn_act_instalar.setEnabled(bool(disponible) and not control.revision_en_curso)
        self.btn_act_instalar.setToolTip("" if puede_instalar() else "La instalación automática solo funciona en el ejecutable")
        if control.ultima_revision is not None:
            self.lbl_act_revision.setText(f"Última revisión: {control.ultima_revision:%d-%m-%Y %H:%M}")
        self._terminar_busqueda()

    def _instalar_actualizacion(self):
        from src.ui.marco.dialogo_actualizacion import abrir_dialogo_actualizacion
        abrir_dialogo_actualizacion(self.window())

    @staticmethod
    def _titulo_pagina(lay, titulo, info):
        lbl = QLabel(titulo)
        lbl.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {estilo_com.TINTA};")
        sub = QLabel(info)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px;")
        lay.addWidget(lbl)
        lay.addWidget(sub)

    @staticmethod
    def _boton(texto, icono, tipo="secundario"):
        """Botón de Configuración: 'primario' (azul Volvo), 'secundario' (borde fino) o 'texto'."""
        btn = QPushButton(texto)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if tipo == "primario":
            btn.setIcon(qta.icon(icono, color='white'))
            qss = ("QPushButton { background: #1B2B4E; color: white; border: 1px solid #1B2B4E; }"
                   "QPushButton:hover { background: #2C4A80; border-color: #2C4A80; }")
        elif tipo == "texto":
            btn.setIcon(qta.icon(icono, color="#1B2B4E"))
            qss = ("QPushButton { background: transparent; color: #1B2B4E; border: 1px solid transparent; }"
                   "QPushButton:hover { background: #E6ECF6; }")
        else:
            btn.setIcon(qta.icon(icono, color="#1B2B4E"))
            qss = (f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; }}"
                   f"QPushButton:hover {{ background: {estilo_com.SUPERFICIE_2}; border-color: {estilo_com.APAGADO}; }}")
        btn.setStyleSheet(qss.replace("QPushButton {", "QPushButton { border-radius: 9px; padding: 8px 14px; "
                                      "font-size: 13px; font-weight: 600;", 1))
        return btn

    _ENLACES = (("Provisiones", "PROVISIONES_SHAREPOINT_URL", "fa5s.table"),
                ("Reporte Notas de Venta", "REPORTE_NOTAS_VENTAS_URL", "fa5s.file-alt"))

    @staticmethod
    def _marco_lista(nombre):
        marco = QFrame()
        marco.setObjectName(nombre)
        marco.setStyleSheet(f"QFrame#{nombre} {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return marco, lay

    @staticmethod
    def _linea():
        linea = QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet(f"background: {estilo_com.LINEA_SUAVE}; border: none;")
        return linea

    @staticmethod
    def _resumen_url(url):
        if not url:
            return "Sin enlace configurado"
        partes_url = urlparse(url)
        if not partes_url.netloc:
            return url
        tramos = [t for t in partes_url.path.split("/") if t]
        texto = partes_url.netloc
        if tramos:
            texto += " › " + " › ".join(tramos[:2]) + (" › …" if len(tramos) > 2 else "")
        return texto

    def _crear_pagina_enlaces(self):
        pagina, lay = self._pagina()
        self._titulo_pagina(lay, "Enlaces web",
                            "Direcciones de SharePoint y Power BI que usa la aplicación. Pulsa «Editar» solo si cambió alguna.")
        marco, caja = self._marco_lista("listaEnlaces")
        self._filas_enlace = {}
        for i, (nombre, clave, icono) in enumerate(self._ENLACES):
            if i:
                caja.addWidget(self._linea())
            fila = QWidget()
            col = QVBoxLayout(fila)
            col.setContentsMargins(16, 12, 16, 12)
            col.setSpacing(10)
            principal = QHBoxLayout()
            principal.setSpacing(14)
            logo = QLabel()
            logo.setFixedSize(38, 38)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setPixmap(qta.icon(icono, color=VOLVO).pixmap(QSize(16, 16)))
            logo.setStyleSheet(f"background: {VOLVO_SUAVE}; border-radius: 10px; border: none;")
            textos = QVBoxLayout()
            textos.setSpacing(0)
            lbl_nombre = QLabel(nombre)
            lbl_nombre.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {estilo_com.TINTA}; {_SIN_FONDO}")
            lbl_dominio = QLabel("")
            lbl_dominio.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
            textos.addWidget(lbl_nombre)
            textos.addWidget(lbl_dominio)
            pildora = QLabel("")
            btn_editar = self._boton("Editar", 'fa5s.pen', "secundario")
            principal.addWidget(logo)
            principal.addLayout(textos, 1)
            principal.addWidget(pildora)
            principal.addWidget(btn_editar)
            col.addLayout(principal)

            edicion = QWidget()
            fila_edicion = QHBoxLayout(edicion)
            fila_edicion.setContentsMargins(52, 0, 0, 0)
            txt_input = QLineEdit(self.config.get(clave, ""))
            txt_input.setPlaceholderText("https://...")
            btn_listo = self._boton("Listo", 'fa5s.check', "primario")
            fila_edicion.addWidget(txt_input, 1)
            fila_edicion.addWidget(btn_listo)
            edicion.setVisible(False)
            col.addWidget(edicion)
            caja.addWidget(fila)

            self.url_inputs[clave] = txt_input
            self._filas_enlace[clave] = (lbl_dominio, pildora, txt_input)
            btn_editar.clicked.connect(lambda _=False, e=edicion, t=txt_input: (e.setVisible(not e.isVisible()), t.setFocus()))
            btn_listo.clicked.connect(lambda _=False, e=edicion: e.setVisible(False))
            txt_input.textChanged.connect(lambda _t, c=clave: self._actualizar_enlace(c))
            self._actualizar_enlace(clave)
        lay.addWidget(marco)
        lay.addStretch()
        return pagina

    def _actualizar_enlace(self, clave):
        lbl_dominio, pildora, txt_input = self._filas_enlace[clave]
        url = txt_input.text().strip()
        lbl_dominio.setText(self._resumen_url(url))
        if not url:
            texto, fondo, color = "Sin enlace", estilo_com.SUPERFICIE_2, estilo_com.APAGADO
        elif url.startswith(("http://", "https://")):
            texto, fondo, color = "✓ Enlace válido", "#E3F6EE", SUCCESS
        else:
            texto, fondo, color = "✗ Debe empezar con https://", "#FDECEC", DANGER
        pildora.setText(texto)
        pildora.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 11px; padding: 3px 11px; "
                              "font-size: 11px; font-weight: 600; border: none;")
        borde = DANGER if (url and not url.startswith(("http://", "https://"))) else VOLVO
        txt_input.setStyleSheet(
            f"QLineEdit {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {borde}; "
            f"border-radius: 9px; padding: 8px 12px; font-size: 13px; }}")
        txt_input.setToolTip(url)

    def _crear_pagina_avanzado(self):
        pagina, lay = self._pagina()
        self._titulo_pagina(lay, "Herramientas de programador",
                            "Solo visible en modo programador (MODO_PROGRAMADOR en config/settings.py).")

        lay.addWidget(self._crear_tarjeta_datos_prueba())
        lay.addWidget(self._crear_tarjeta_restaurar_demo())
        lay.addStretch()
        return pagina

    def _crear_tarjeta_datos_prueba(self):
        prueba = ajustes.DATOS_DE_PRUEBA
        marco = QFrame()
        marco.setObjectName("tarjetaDatosPrueba")
        marco.setStyleSheet(f"QFrame#tarjetaDatosPrueba {{ background: {estilo_com.SUPERFICIE}; "
                            f"border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(16, 14, 16, 14)
        fila.setSpacing(14)
        textos = QVBoxLayout()
        textos.setSpacing(3)
        titulo = QLabel("Usar datos de prueba")
        titulo.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        detalle = QLabel("Con el interruptor encendido la app lee y escribe en la carpeta datos_prueba (datos inventados) "
                         "y no toca los de SharePoint. Al cambiarlo, la aplicación se reinicia.")
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        self.lbl_estado_datos = QLabel()
        self._marcar_estado_datos(prueba)
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        textos.addWidget(self.lbl_estado_datos)
        fila.addLayout(textos, 1)
        self.sw_datos_prueba = _InterruptorDatos(prueba)
        self.sw_datos_prueba.clicked.connect(self._cambiar_datos_prueba)
        fila.addWidget(self.sw_datos_prueba, 0, Qt.AlignmentFlag.AlignVCenter)
        return marco

    def _marcar_estado_datos(self, prueba):
        texto, color = (("Trabajando con datos falsos", SUCCESS) if prueba
                        else ("Trabajando con datos reales: lo que se guarde queda en producción", DANGER))
        self.lbl_estado_datos.setText(texto)
        self.lbl_estado_datos.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {color}; {_SIN_FONDO}")

    def _cambiar_datos_prueba(self):
        activar = self.sw_datos_prueba.isChecked()

        def deshacer():
            self.sw_datos_prueba.setChecked(not activar)

        if activar and not ajustes.hay_datos_prueba():
            QMessageBox.warning(self, "Datos de prueba",
                                f"No se encuentra la carpeta de datos de prueba:\n{ajustes.DIR_DATOS_PRUEBA}")
            deshacer()
            return
        destino = "datos falsos (carpeta datos_prueba)" if activar else "los datos reales de SharePoint"
        respuesta = QMessageBox.question(
            self, "Cambiar de datos",
            f"La aplicación se reiniciará y pasará a usar {destino}.\n\n"
            "Asegúrate de no tener cambios sin guardar. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            deshacer()
            return
        try:
            ajustes.guardar_datos_prueba_activo(activar)
        except OSError as e:
            QMessageBox.critical(self, "Datos de prueba", f"No se pudo guardar el cambio:\n{e}")
            deshacer()
            return
        # close() pasa por MainWindow.closeEvent: guarda geometría/columnas y detiene los hilos.
        self.window().close()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def _crear_tarjeta_restaurar_demo(self):
        disponible = ajustes.DATOS_DE_PRUEBA and ajustes.hay_base_demo()
        marco = QFrame()
        marco.setObjectName("tarjetaRestaurarDemo")
        marco.setStyleSheet(f"QFrame#tarjetaRestaurarDemo {{ background: {estilo_com.SUPERFICIE}; "
                            f"border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(16, 14, 16, 14)
        fila.setSpacing(14)
        textos = QVBoxLayout()
        textos.setSpacing(3)
        titulo = QLabel("Restaurar datos de demostración")
        titulo.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        detalle = QLabel("Deja datos_prueba como el original: toda la flota facturada menos una, sin las unidades importadas "
                         "ni los cambios hechos en la demo, y con Detalle_demo.xlsx listo para importar. "
                         "Al terminar, la aplicación se reinicia.")
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        if not disponible:
            nota = QLabel("Disponible con el interruptor de datos de prueba encendido y la carpeta datos_prueba_base presente.")
            nota.setWordWrap(True)
            nota.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {DANGER}; {_SIN_FONDO}")
            textos.addWidget(nota)
        fila.addLayout(textos, 1)
        self.btn_restaurar_demo = self._boton(" Restaurar y reiniciar", "fa5s.undo")
        self.btn_restaurar_demo.setEnabled(disponible)
        self.btn_restaurar_demo.clicked.connect(self._restaurar_datos_demo)
        fila.addWidget(self.btn_restaurar_demo, 0, Qt.AlignmentFlag.AlignVCenter)
        return marco

    def _restaurar_datos_demo(self):
        if not ajustes.DATOS_DE_PRUEBA:
            return
        respuesta = QMessageBox.question(
            self, "Restaurar datos de demostración",
            "Se reemplazarán los archivos de la carpeta datos_prueba por los originales y la aplicación se reiniciará.\n\n"
            "Los datos reales no se tocan. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        try:
            restaurar_datos_demostracion(ajustes.DIR_DATOS_PRUEBA_BASE, ajustes.DIR_DATOS_PRUEBA)
        except OSError as e:
            QMessageBox.critical(self, "Restaurar datos de demostración",
                                 f"No se pudo restaurar:\n{e}\n\nCierra los Excel abiertos de la carpeta datos_prueba e inténtalo de nuevo.")
            return
        self.window().close()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    @staticmethod
    def _qss_campo():
        return (f"QLineEdit {{ background: {estilo_com.SUPERFICIE_2}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
                "border-radius: 10px; padding: 9px 12px; font-size: 13px; }"
                f"QLineEdit:focus {{ border-color: {VOLVO}; }}")

    # ------------------------------------------------------------------
    # Carpeta de datos: una sola elección y el resto de rutas se completa solo
    # ------------------------------------------------------------------
    def _crear_grupo_carpeta_datos(self):
        grupo, lay = self._pagina()

        carpeta_inicial = self.config.get("DATA_DIR") or os.path.dirname(self.config.get("EXCEL_PATH", "") or "")
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaCarpeta")
        tarjeta.setStyleSheet(f"QFrame#tarjetaCarpeta {{ background: {estilo_com.SUPERFICIE}; "
                              f"border: 1px solid {estilo_com.LINEA}; border-radius: 14px; }}")
        col = QVBoxLayout(tarjeta)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent; border: none;")
        fila_ruta = QHBoxLayout(cuerpo)
        fila_ruta.setContentsMargins(18, 16, 18, 14)
        fila_ruta.setSpacing(14)
        insignia = QLabel()
        insignia.setFixedSize(46, 46)
        insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        insignia.setPixmap(qta.icon('fa5s.folder-open', color='white').pixmap(QSize(20, 20)))
        insignia.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1B2B4E, stop:1 #2C4A80); "
                               "border-radius: 13px; border: none;")
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(admin_estilo.etiqueta_caja("CARPETA DE DATOS"))
        self.data_dir_input = QLineEdit(carpeta_inicial)
        self.data_dir_input.setPlaceholderText("Carpeta que contiene Registro Maestro.csv y los demás archivos")
        self.data_dir_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {estilo_com.TINTA}; border: none; padding: 2px 0; "
            "font-size: 14px; font-weight: 700; }")
        self.data_dir_input.setCursorPosition(0)
        textos.addWidget(self.data_dir_input)
        self.lbl_resumen_rutas = QLabel("")
        fila_ruta.addWidget(insignia)
        fila_ruta.addLayout(textos, 1)
        col.addWidget(cuerpo)
        col.addWidget(self._linea())

        botones = QWidget()
        botones.setStyleSheet("background: transparent; border: none;")
        fila = QHBoxLayout(botones)
        fila.setContentsMargins(18, 12, 18, 12)
        fila.setSpacing(8)
        btn_auto = self._boton("Autodetectar", 'fa5s.magic', "primario")
        btn_auto.setToolTip("Busca cada archivo dentro de la carpeta elegida")
        btn_auto.clicked.connect(lambda: self._autodetectar())
        btn_examinar = self._boton("Examinar", 'fa5s.folder-open', "primario")
        btn_examinar.clicked.connect(self._elegir_carpeta_datos)
        btn_abrir = self._boton("Abrir carpeta", 'fa5s.external-link-alt', "primario")
        btn_abrir.clicked.connect(self._abrir_carpeta_datos)
        btn_ayuda = self._boton("¿Cómo me conecto?", 'fa5s.question-circle', "primario")
        btn_ayuda.clicked.connect(lambda: GuiaConexionDialog(self).exec())
        for btn in (btn_auto, btn_examinar, btn_abrir, btn_ayuda):
            fila.addWidget(btn)
        fila.addStretch()
        col.addWidget(botones)

        pie = QWidget()
        pie.setObjectName("pieCarpeta")
        pie.setStyleSheet(f"QWidget#pieCarpeta {{ background: {estilo_com.SUPERFICIE_2}; border: none; "
                          "border-bottom-left-radius: 13px; border-bottom-right-radius: 13px; }")
        fila_pie = QHBoxLayout(pie)
        fila_pie.setContentsMargins(18, 6, 12, 6)
        self.lbl_resumen_rutas.setToolTip("Elige la carpeta una vez y la app encuentra el resto")
        fila_pie.addWidget(self.lbl_resumen_rutas)
        fila_pie.addStretch(1)
        col.addWidget(pie)
        self.data_dir_input.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(tarjeta)

        self.caja_estado_rutas = QVBoxLayout()
        self.caja_estado_rutas.setSpacing(12)
        lay.addLayout(self.caja_estado_rutas)
        lay.addStretch()
        return grupo

    def _elegir_carpeta_datos(self):
        actual = self.data_dir_input.text().strip()
        carpeta = QFileDialog.getExistingDirectory(
            self, "Selecciona la carpeta de datos", actual if os.path.isdir(actual) else "")
        if carpeta:
            self.data_dir_input.setText(os.path.normpath(carpeta))
            self._autodetectar()

    def _abrir_carpeta_datos(self):
        carpeta = self.data_dir_input.text().strip()
        if os.path.isdir(carpeta):
            os.startfile(carpeta)

    def _asignar_ruta(self, clave, ruta):
        ruta = os.path.normpath(ruta)
        if clave in self.path_inputs:
            self.path_inputs[clave].setText(ruta)
        else:
            self._rutas_extra[clave] = ruta

    def _autodetectar(self):
        """Completa todas las rutas a partir de la carpeta de datos; si está
        vacía o no existe, primero la busca desde la carpeta del usuario."""
        base = self.data_dir_input.text().strip()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if not os.path.isdir(base):
                base = rutas.buscar_carpeta_de_datos(os.path.expanduser("~")) or ""
            encontrados = rutas.descubrir_archivos(base, subir=2) if base else {}
        finally:
            QApplication.restoreOverrideCursor()
        if not encontrados:
            QMessageBox.information(
                self, "Autodetectar archivos",
                "No encontré los archivos de la aplicación. Elige a mano la carpeta que contiene Registro Maestro.csv.")
            return
        self.data_dir_input.setText(os.path.normpath(base))
        for clave, ruta in encontrados.items():
            self._asignar_ruta(clave, ruta)
        self._refrescar_estado_rutas()

    def _ruta_de(self, clave):
        if clave in self.path_inputs:
            return self.path_inputs[clave].text().strip()
        return self._rutas_extra.get(clave, "")

    @staticmethod
    def _tamano_legible(bytes_):
        if bytes_ >= 1024 * 1024:
            return f"{bytes_ / (1024 * 1024):.1f} MB"
        return f"{max(1, round(bytes_ / 1024))} KB"

    _GRUPOS_ARCHIVOS = (
        ("Base de datos principal", ("EXCEL_PATH", "PROVISION_EXCEL_PATH", "INSTALACIONES_PATH", "POWERBI_EXCEL_PATH")),
        ("Registros y contactos", ("LOG_CSV_PATH", "DELETED_LOG_EXCEL_PATH", "CONTACTOS_EXCEL_PATH", "CORREOS_EXCEL_PATH",
                                    "EJECUTIVOS_PATH", "METAS_VC_PATH", "CASOS_BAJA_CM_PATH", "FACTURACION_MANUAL_PATH")),
    )

    def _refrescar_estado_rutas(self):
        """Dos tablas de estado: una fila por archivo con check, nombre, fecha y tamaño."""
        caja = self.caja_estado_rutas
        while caja.count():
            item = caja.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        faltan, total = [], 0
        for n_grupo, (titulo_grupo, claves) in enumerate(self._GRUPOS_ARCHIVOS):
            marco, lay_marco = self._marco_lista(f"grupoArchivos{n_grupo}")
            encabezado = QWidget()
            encabezado.setStyleSheet(f"background: {estilo_com.SUPERFICIE_2}; border-top-left-radius: 12px; border-top-right-radius: 12px;")
            fila_enc = QHBoxLayout(encabezado)
            fila_enc.setContentsMargins(16, 7, 16, 7)
            for texto, alinea in ((titulo_grupo.upper(), Qt.AlignmentFlag.AlignLeft), ("MODIFICADO · TAMAÑO", Qt.AlignmentFlag.AlignRight)):
                lbl = QLabel(texto)
                lbl.setAlignment(alinea)
                lbl.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
                fila_enc.addWidget(lbl, 1)
            lay_marco.addWidget(encabezado)
            for clave in claves:
                etiqueta, nombre_estandar, obligatorio = rutas.ARCHIVOS_DE_DATOS[clave]
                ruta = self._ruta_de(clave)
                existe, tamano, modificado = rutas.estado_archivo(ruta) if ruta else (False, 0, 0.0)
                if obligatorio or ruta:
                    total += 1
                    if not existe:
                        faltan.append(etiqueta)
                if existe:
                    marca, color, fondo = "✓", SUCCESS, "#E3F6EE"
                    fecha = datetime.fromtimestamp(modificado).strftime('%d-%m-%Y %H:%M')
                    detalle = f"{fecha}   ·   {self._tamano_legible(tamano)}"
                elif ruta:
                    marca, color, fondo, detalle = "✕", DANGER, "#FDECEC", "No se encuentra en la ruta indicada"
                elif obligatorio:
                    marca, color, fondo, detalle = "✕", DANGER, "#FDECEC", "Sin ruta"
                else:
                    marca, color, fondo, detalle = "–", estilo_com.APAGADO, estilo_com.SUPERFICIE_2, "Sin ruta"
                lay_marco.addWidget(self._linea())
                fila_w = QWidget()
                fila_w.setMinimumHeight(50)
                fila = QHBoxLayout(fila_w)
                fila.setContentsMargins(16, 8, 16, 8)
                fila.setSpacing(12)
                lbl_marca = QLabel(marca)
                lbl_marca.setFixedSize(22, 22)
                lbl_marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl_marca.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 11px; font-size: 11px; font-weight: 700; border: none;")
                textos = QVBoxLayout()
                textos.setSpacing(0)
                lbl_nombre = QLabel(etiqueta)
                lbl_nombre.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {estilo_com.TINTA}; {_SIN_FONDO}")
                lbl_archivo = QLabel(os.path.basename(ruta) if ruta else nombre_estandar)
                lbl_archivo.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
                textos.addWidget(lbl_nombre)
                textos.addWidget(lbl_archivo)
                lbl_detalle = QLabel(detalle)
                lbl_detalle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                lbl_detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO if existe or not ruta else DANGER}; {_SIN_FONDO}")
                fila.addWidget(lbl_marca)
                fila.addLayout(textos, 1)
                if not obligatorio:
                    lbl_op = QLabel("Opcional")
                    lbl_op.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {estilo_com.APAGADO}; border: 1px solid {estilo_com.LINEA}; "
                                         "border-radius: 6px; padding: 0 6px; background: transparent;")
                    fila.addWidget(lbl_op)
                fila.addWidget(lbl_detalle)
                lay_marco.addWidget(fila_w)
            caja.addWidget(marco)
        n_ok = total - len(faltan)
        if faltan:
            self.lbl_resumen_rutas.setText(f"✕  Faltan {len(faltan)} de {total}")
            self.lbl_resumen_rutas.setToolTip("Faltan: " + ", ".join(faltan))
            self.lbl_resumen_rutas.setStyleSheet(
                f"background: #FDECEC; color: {DANGER}; font-weight: 700; font-size: 12px; border-radius: 12px; padding: 5px 13px;")
        else:
            self.lbl_resumen_rutas.setText(f"✓  {total} de {total} archivos disponibles")
            self.lbl_resumen_rutas.setToolTip("")
            self.lbl_resumen_rutas.setStyleSheet(
                f"background: #E3F6EE; color: {SUCCESS}; font-weight: 700; font-size: 12px; border-radius: 12px; padding: 5px 13px;")
        admin_estilo.fijar_badge(self._badges[0], n_ok)
        self._pastillas[0] = f"{n_ok} de {total} disponibles"
        self._mostrar_pastilla(0)

    def _crear_grupo_escala(self):
        grupo, lay = self._pagina()
        gestor = GestorTema.instancia()
        carpeta_assets = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaApariencia")
        tarjeta.setStyleSheet(f"QFrame#tarjetaApariencia {{ background: {estilo_com.SUPERFICIE}; "
                              f"border: 1px solid {estilo_com.LINEA}; border-radius: 14px; }}")
        capas = QVBoxLayout(tarjeta)
        capas.setContentsMargins(0, 0, 0, 0)
        capas.setSpacing(0)
        # Tema y tamaño van lado a lado; la foto del menú, debajo, con todo el ancho
        columnas = QHBoxLayout()
        columnas.setSpacing(0)
        capas.addLayout(columnas)
        fila_foto = QHBoxLayout()
        fila_foto.setSpacing(0)
        division_h = QFrame()
        division_h.setFixedHeight(1)
        division_h.setStyleSheet(f"background: {estilo_com.LINEA}; border: none;")
        capas.addWidget(division_h)
        capas.addLayout(fila_foto)

        def columna(titulo, estiramiento, destino=None):
            caja = QWidget()
            caja.setStyleSheet("background: transparent; border: none;")
            lay_col = QVBoxLayout(caja)
            lay_col.setContentsMargins(22, 20, 22, 22)
            lay_col.setSpacing(14)
            lbl = QLabel(titulo)
            lbl.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {estilo_com.TINTA};")
            lay_col.addWidget(lbl)
            destino = columnas if destino is None else destino
            if destino.count():
                division = QFrame()
                division.setFixedWidth(1)
                division.setStyleSheet(f"background: {estilo_com.LINEA}; border: none;")
                destino.addWidget(division)
            destino.addWidget(caja, estiramiento)
            return lay_col

        col_tema = columna("Tema", 10)
        self._tarjetas_tema = {}
        for modo, titulo, detalle in ((CLARO, "Claro", "Fondo blanco"), (OSCURO, "Oscuro", "Menos brillo")):
            opcion = _OpcionCompacta(_MiniTema(modo == OSCURO), titulo, detalle)
            opcion.clicked.connect(lambda m=modo, o=opcion: self._aplicar_tema_animado(m, o))
            self._tarjetas_tema[modo] = opcion
            col_tema.addWidget(opcion)
        col_tema.addStretch()
        gestor.tema_cambiado.connect(self._marcar_tema)
        self._marcar_tema(gestor.modo)

        col_tam = columna("Tamaño de la interfaz", 12)
        nivel_actual = get_nivel_escala()
        puntos = {"pequeno": 12, "mediano": 15}
        for clave, (nombre, factor) in NIVELES_ESCALA.items():
            opcion = _OpcionCompacta(_MiniTamano(puntos[clave]), nombre, f"{round(factor * 100)} % del tamaño base")
            opcion.marcar(clave == nivel_actual)
            if clave != nivel_actual:
                opcion.clicked.connect(lambda c=clave: self._cambiar_escala(c))
            else:
                opcion.setCursor(Qt.CursorShape.ArrowCursor)
            col_tam.addWidget(opcion)
        col_tam.addStretch()

        col_foto = columna("Foto del menú lateral", 1, fila_foto)
        grilla = QGridLayout()
        grilla.setSpacing(10)
        self._tarjetas_foto = {}
        opciones = [(menu_fotos.ALEATORIO, "Aleatorio")] + list(menu_fotos.FOTOS)
        modo_actual = menu_fotos.get_modo()
        for i, (clave, nombre) in enumerate(opciones):
            ids = ["puente", "reflejo", "polvo"] if clave == menu_fotos.ALEATORIO else [clave]
            mosaico = _MiniaturaFoto(carpeta_assets, ids, nombre, mezclar=clave == menu_fotos.ALEATORIO)
            mosaico.marcar(clave == modo_actual)
            mosaico.clicked.connect(lambda c=clave: self._elegir_foto_menu(c))
            self._tarjetas_foto[clave] = mosaico
            grilla.addWidget(mosaico, i // 4, i % 4)
        for col in range(4):
            grilla.setColumnStretch(col, 1)
        col_foto.addLayout(grilla)
        col_foto.addStretch()

        lay.addWidget(tarjeta)
        lay.addStretch()
        return grupo
    def _elegir_foto_menu(self, clave):
        menu_fotos.set_modo(clave)
        for k, tarjeta in self._tarjetas_foto.items():
            tarjeta.marcar(k == clave)
        ventana = self.window()
        if hasattr(ventana, "aplicar_foto_menu"):
            ventana.aplicar_foto_menu(animado=True)

    def _aplicar_tema_animado(self, modo, origen):
        """Misma transición del botón de tema de la barra superior, abierta desde la tarjeta elegida."""
        ventana = self.window()
        if hasattr(ventana, "_on_boton_tema"):
            ventana._on_boton_tema(modo == OSCURO, origen)
        else:
            GestorTema.instancia().aplicar(modo)

    def _marcar_tema(self, modo):
        for clave, tarjeta in self._tarjetas_tema.items():
            tarjeta.marcar(clave == modo)

    def _cambiar_escala(self, nivel):
        nombre = NIVELES_ESCALA[nivel][0]
        reply = QMessageBox.question(self, "Cambiar tamaño de la interfaz",
            f"La aplicación se reiniciará para aplicar el tamaño \"{nombre}\".\n\n"
            "Asegúrate de no tener cambios sin guardar. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        set_nivel_escala(nivel)
        # close() pasa por MainWindow.closeEvent: guarda geometría/columnas y detiene los hilos.
        self.window().close()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def _validate_path_input(self, txt_input):
        ruta = txt_input.text().strip()
        if not ruta or os.path.exists(ruta):
            txt_input.setStyleSheet("""
                QLineEdit { border: 1.5px solid #10B981; background-color: #F0FDF4; color: #166534; border-radius: 6px; padding: 6px 10px; font-weight: bold; font-size: 12px; }
            """)
            txt_input.setToolTip(" Archivo Excel encontrado en esta ruta." if ruta else "Ruta local vacía.")
        else:
            txt_input.setStyleSheet("""
                QLineEdit { border: 2px solid #EF4444; background-color: #FEF2F2; color: #991B1B; border-radius: 6px; padding: 6px 10px; font-weight: bold; font-size: 12px; }
            """)
            txt_input.setToolTip(" ALERTA: No se encontró el archivo en esta ruta local.")

    def _create_status_card(self, title, icon_name, icon_color, initial_value):
        frame = QFrame()
        frame.setObjectName("tarjetaEstadoConfig")
        frame.setStyleSheet("QFrame#tarjetaEstadoConfig { background: transparent; border: none; }")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(26, 26)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pintar_icono_estado(icon_lbl, icon_name, icon_color)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 10px; font-weight: 600; border: none; background: transparent;")
        val_lbl = QLabel(initial_value)
        val_lbl.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; font-weight: 800; border: none; background: transparent;")
        texto = QVBoxLayout()
        texto.setSpacing(0)
        texto.addWidget(title_lbl)
        texto.addWidget(val_lbl)

        layout.addWidget(icon_lbl)
        layout.addLayout(texto, 1)
        return {'frame': frame, 'val_lbl': val_lbl, 'icon_color': icon_color, 'icon_lbl': icon_lbl, 'icon_name': icon_name}

    @staticmethod
    def _pintar_icono_estado(icon_lbl, icon_name, icon_color):
        icon_lbl.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(QSize(13, 13)))
        tono = QColor(icon_color)
        fondo = "#E6ECF6" if icon_color == "#1B2B4E" else f"rgba({tono.red()},{tono.green()},{tono.blue()},34)"
        icon_lbl.setStyleSheet(f"background-color: {fondo}; border-radius: 8px; border: none;")

    def update_health_panel(self):
        if hasattr(self.data_manager, 'get_system_health'):
            health = self.data_manager.get_system_health()
            self.card_db['val_lbl'].setText(health.get('db_status', 'N/A'))
            self.card_rows['val_lbl'].setText(str(health.get('db_rows', 0)))
            self.card_sync['val_lbl'].setText(health.get('last_modified', 'N/A'))
            self.card_ram['val_lbl'].setText(health.get('ram_usage', 'N/A'))
            self.card_load_time['val_lbl'].setText(health.get('load_time', 'N/A'))
            self.card_logs['val_lbl'].setText(health.get('log_status', 'N/A'))
            # El ícono de logs toma el color del estado: verde si está sano, rojo o ámbar si hay alertas
            self._pintar_icono_estado(self.card_logs['icon_lbl'], self.card_logs['icon_name'], health.get('log_color', '#1B2B4E'))
            self.card_logs['val_lbl'].setStyleSheet(f"color: {health.get('log_color', TEXT_PRIMARY)}; font-size: 12px; font-weight: 800; border: none; background: transparent;")
            self.last_errors = health.get('recent_errors', [])
            self.last_alerts = health.get('recent_alerts', [])
            hay_alertas = len(self.last_alerts) > 0
            self.btn_view_errors.setVisible(hay_alertas)
            self.btn_ver_alertas.setVisible(hay_alertas)

    def force_refresh(self):
        if self.btn_refresh.property("girando"):
            return
        self.btn_refresh.setProperty("girando", True)
        self.btn_refresh.setText("  Actualizando...")
        icono = qta.icon('fa5s.sync-alt', color='white').pixmap(QSize(16, 16))
        giro = QVariantAnimation(self)
        giro.setStartValue(0.0)
        giro.setEndValue(720.0)
        giro.setDuration(900)
        giro.setEasingCurve(QEasingCurve.Type.InOutSine)

        def _girar(grados):
            rotado = icono.transformed(QTransform().rotate(grados), Qt.TransformationMode.SmoothTransformation)
            recorte = rotado.copy((rotado.width() - 16) // 2, (rotado.height() - 16) // 2, 16, 16)
            self.btn_refresh.setIcon(QIcon(recorte))

        def _terminar():
            self.update_health_panel()
            self.btn_refresh.setIcon(qta.icon('fa5s.check', color='white'))
            self.btn_refresh.setText("  Estado actualizado")
            QTimer.singleShot(1200, _restaurar)

        def _restaurar():
            self.btn_refresh.setIcon(qta.icon('fa5s.sync-alt', color='white'))
            self.btn_refresh.setText("  Actualizar estado")
            self.btn_refresh.setProperty("girando", False)

        giro.valueChanged.connect(_girar)
        giro.finished.connect(_terminar)
        giro.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _show_error_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Alertas y errores del registro")
        dialog.resize(800, 500)
        dialog.setStyleSheet(f"background-color: {SURFACE};")

        layout = QVBoxLayout(dialog)
        lbl_info = QLabel("Lo que el sistema anotó en logs/sistema.log (lo más reciente primero):")
        lbl_info.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2937;")
        layout.addWidget(lbl_info)

        txt_display = QTextEdit()
        txt_display.setReadOnly(True)
        txt_display.setStyleSheet("background-color: #111827; color: #F3F4F6; font-family: Consolas; font-size: 12px; padding: 10px; border-radius: 6px;")

        colores = {"WARNING": "#FBBF24", "ERROR": "#F87171", "CRITICAL": "#F87171"}
        etiquetas = {"WARNING": "ALERTA", "ERROR": "ERROR", "CRITICAL": "ERROR GRAVE"}
        bloques = []
        for a in self.last_alerts:
            bloques.append(
                f"<p><span style='color:#9CA3AF'>[{html.escape(a['hora'])}]</span> "
                f"<b style='color:{colores.get(a['nivel'], '#F3F4F6')}'>{etiquetas.get(a['nivel'], a['nivel'])}</b><br>"
                f"{html.escape(a['mensaje'])}</p>")
        txt_display.setHtml("".join(bloques) or "<p>Sin alertas.</p>")
        layout.addWidget(txt_display)

        footer = QHBoxLayout()
        btn_resolve = QPushButton(" Limpiar Registro")
        btn_resolve.setIcon(qta.icon('fa5s.broom', color='white'))
        btn_resolve.setStyleSheet(f"background-color: {SUCCESS}; color: white; border-radius: 4px; font-weight: bold; padding: 5px 15px;")
        btn_resolve.clicked.connect(lambda: self._clear_error_logs(dialog))
        
        btn_close = QPushButton("Cerrar")
        ThemeManager.apply_secondary_button(btn_close)
        btn_close.clicked.connect(dialog.accept)
        
        footer.addWidget(btn_resolve)
        footer.addStretch()
        footer.addWidget(btn_close)
        layout.addLayout(footer)
        dialog.exec()

    def _clear_error_logs(self, dialog):
        log_path = RUTA_LOG
        if os.path.exists(log_path):
            try:
                with open(log_path, 'w', encoding='utf-8') as f: f.write("")
                logger.info("Registro limpiado desde Configuración")
                QMessageBox.information(self, "Registro Limpio", "El sistema vuelve a estar en estado Saludable.")
            except Exception as e:
                QMessageBox.warning(self, "Aviso", f"Error: {e}")
        dialog.accept()        
        self.force_refresh()   

    def _browse_file(self, config_key, text_input):
        # LOG_CSV_PATH y CASOS_BAJA_CM_PATH apuntan a CSV (historial y casos
        # de Revision CM, ver cm_bajas_service.py); CORREOS_EXCEL_PATH tambien
        # desde la migracion B-5.2 (18-09-2026, Correos.xlsx -> Correos.csv) --
        # el nombre de la clave de configuracion se mantiene igual para no
        # romper app_config.json existentes, solo cambio el formato del
        # archivo al que apunta. El resto sigue siendo *.xlsx/*.xlsm como siempre.
        campos_csv = ("LOG_CSV_PATH", "CASOS_BAJA_CM_PATH", "CORREOS_EXCEL_PATH", "METAS_VC_PATH")
        filtro = "Archivo CSV (*.csv)" if config_key in campos_csv else "Archivos Excel (*.xlsx *.xlsm)"
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo", os.path.dirname(text_input.text()) if text_input.text() else "", filtro)
        if ruta:
            text_input.setText(ruta.replace("/", "\\"))
            self._validate_path_input(text_input)

    def _reemplazar_archivo_copia(self, config_key, text_input):
        """Reemplaza el CONTENIDO del archivo ya configurado en `config_key`
        por una copia nueva elegida por el usuario, sin cambiar la ruta
        guardada (a diferencia de _browse_file). Pensado para BBDD Clientes
        CM: la ruta apunta siempre al mismo lugar (SharePoint/OneDrive
        sincronizado), y periódicamente llega una copia nueva de Power BI
        que hay que dejar ahí mismo."""
        ruta_actual = text_input.text().strip()
        if not ruta_actual:
            QMessageBox.warning(self, "Ruta no configurada",
                "Primero elige la carpeta de datos (o usa 'Autodetectar archivos') y guarda los cambios, "
                "antes de poder reemplazar su contenido.")
            return

        ruta_nueva, _ = QFileDialog.getOpenFileName(self, "Selecciona la copia nueva",
            os.path.dirname(ruta_actual) if os.path.exists(os.path.dirname(ruta_actual)) else "",
            "Archivos Excel (*.xlsx *.xlsm)")
        if not ruta_nueva:
            return

        if os.path.abspath(ruta_nueva) == os.path.abspath(ruta_actual):
            QMessageBox.warning(self, "Mismo archivo", "El archivo seleccionado es el mismo que ya está configurado.")
            return

        # Validacion ligera: confirma que la copia nueva es un Excel legible
        # y que su primera hoja (misma que usa powerbi_cache_service, NO
        # wb.active) tiene columna 'CDB' -- evita reemplazar el archivo real
        # por algo con el formato equivocado.
        try:
            wb = openpyxl.load_workbook(ruta_nueva, read_only=True, data_only=True)
            ws = wb[wb.sheetnames[0]]
            primera_fila = next(ws.iter_rows(values_only=True, max_row=1), ())
            wb.close()
            headers = [str(h).strip() if h is not None else "" for h in primera_fila]
        except Exception as e:
            QMessageBox.critical(self, "Archivo inválido", f"No se pudo leer el archivo seleccionado como Excel:\n\n{e}")
            return

        if "CDB" not in headers:
            QMessageBox.critical(self, "Formato inesperado",
                "El archivo seleccionado no tiene una columna 'CDB' en su primera hoja.\n\n"
                "No parece ser una copia válida de BBDD Clientes CM. No se reemplazó nada.")
            return

        reply = QMessageBox.question(self, "Confirmar actualización",
            f"Esto reemplazará el contenido de:\n{ruta_actual}\n\ncon:\n{ruta_nueva}\n\n"
            "Se guardará una copia de seguridad del archivo actual antes de reemplazarlo.\n\n¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.exists(ruta_actual):
                writer_backup = ExcelWriter()
                writer_backup._crear_backup(ruta_actual)
                if not writer_backup.last_backup_ok:
                    QMessageBox.critical(self, "Actualización cancelada",
                        "No se pudo crear un respaldo del archivo actual antes de reemplazarlo.\n\n"
                        "Para evitar perder el archivo actual sin posibilidad de deshacerlo, "
                        "la actualización fue cancelada. No se modificó ningún archivo.")
                    return

            # shutil.copy (NO copy2): necesitamos que el archivo destino
            # quede con fecha de modificación de AHORA, no la fecha original
            # de la copia nueva -- el cache CSV de powerbi_cache_service se
            # invalida comparando esa fecha contra la del cache existente.
            shutil.copy(ruta_nueva, ruta_actual)

            QProcess.startDetached(sys.executable, sys.argv)
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo reemplazar el archivo:\n\n{e}")

    def _restore_backup(self):
        backup_dir = os.path.join(os.getcwd(), 'data', 'backups')
        if not os.path.exists(backup_dir): return QMessageBox.information(self, "Sin Backups", "Aún no hay copias de seguridad.")

        # Fase 2 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): el filtro y
        # la extension esperada se derivan de EXCEL_PATH en vez de
        # hardcodear ".xlsx", asi soporta ambos formatos sin duplicar esta
        # pantalla. Filtrar por la extension ACTUAL de EXCEL_PATH (no ambas
        # a la vez) evita mezclar un backup .csv con un destino .xlsx o
        # viceversa -- un backup nunca cambia de formato al restaurarse.
        extension_actual = os.path.splitext(EXCEL_PATH)[1] or ".xlsx"
        ruta_backup, _ = QFileDialog.getOpenFileName(
            self, "Selecciona copia de seguridad", backup_dir,
            f"Copias de seguridad (*{extension_actual})",
        )
        if ruta_backup:
            # La carpeta de backups mezcla copias de PruebasFM, Provisiones,
            # Contactos, etc. Esta funcion solo restaura PruebasFM (xlsx o
            # csv, segun EXCEL_PATH), asi que se bloquea si el backup
            # elegido pertenece a otro archivo (evita sobrescribir la base
            # de datos con la estructura equivocada).
            nombre_base_excel = os.path.splitext(os.path.basename(EXCEL_PATH))[0]
            nombre_backup = os.path.basename(ruta_backup)
            if not (nombre_backup.startswith(f"{nombre_base_excel}_backup_")
                    or (nombre_base_excel in ("RM_JAVI", "Registro Maestro")
                        and nombre_backup.startswith(("RM_JAVI_backup_", "Registro Maestro_backup_", "PruebasFM_backup_")))):
                QMessageBox.critical(self, "Backup incompatible",
                    f"El archivo seleccionado ('{nombre_backup}') no es una copia de seguridad de la base de datos principal ({os.path.basename(EXCEL_PATH)}).\n\n"
                    "Restaurarlo aquí sobrescribiría la base de datos con datos de otro archivo. Selecciona un backup que comience con "
                    f"'{nombre_base_excel}_backup_'.")
                return

            reply = QMessageBox.question(self, 'Advertencia Crítica', f"¿Restaurar?\n\nArchivo: {nombre_backup}\nEsto sobrescribirá tu base de datos actual.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    # Antes de sobrescribir EXCEL_PATH con el backup elegido,
                    # se respalda el estado ACTUAL (mismo mecanismo que ya
                    # usa ExcelWriter en el resto de la app) para poder
                    # deshacer la restauracion si hiciera falta. Si ese
                    # backup previo falla, se cancela todo sin tocar el
                    # archivo real.
                    writer_backup = ExcelWriter()
                    writer_backup._crear_backup(EXCEL_PATH)
                    if not writer_backup.last_backup_ok:
                        QMessageBox.critical(self, "Restauración cancelada",
                            "No se pudo crear un respaldo del estado actual antes de restaurar.\n\n"
                            "Para evitar perder el estado actual sin posibilidad de deshacerlo, "
                            "la restauración fue cancelada. No se modificó ningún archivo.")
                        return

                    shutil.copy2(ruta_backup, EXCEL_PATH)
                    QProcess.startDetached(sys.executable, sys.argv)
                    QApplication.quit()
                except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def _save_changes(self):
        hay_error = False
        
        for key, txt_input in self.path_inputs.items(): 
            ruta = txt_input.text().strip()
            if ruta and not os.path.exists(ruta):
                hay_error = True
                
        for key, txt_input in self.url_inputs.items():
            url = txt_input.text().strip()
            if url and not (url.startswith("http://") or url.startswith("https://")):
                hay_error = True
                
        if hay_error:
            reply = QMessageBox.warning(self, "Rutas o URLs Inválidas", 
                                        "Atención: Una o más casillas tienen datos incorrectos (marcadas en rojo).\n\n"
                                        "Si guardas y reinicias, el sistema puede fallar al cargar esas fuentes.\n¿Deseas guardar de todos modos?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: return

        for key, txt_input in self.path_inputs.items():
            self.config[key] = txt_input.text().strip()
        self.config.update(self._rutas_extra)
        self.config["DATA_DIR"] = self.data_dir_input.text().strip()
        for key, txt_input in self.url_inputs.items():
            self.config[key] = txt_input.text().strip()
            
        save_config(self.config)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Configuración Guardada")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Las rutas y enlaces se han actualizado exitosamente.\n\nLa aplicación se reiniciará automáticamente para aplicar los cambios.")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()
