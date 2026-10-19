import os
import sys
import re
import time
import pandas as pd
import qtawesome as qta
import pythoncom
import win32com.client
from datetime import datetime, date

from PyQt6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QTableView, QHeaderView,
    QProgressBar, QComboBox, QWidget, QApplication, QMenu, QTabWidget, QScrollArea, QButtonGroup, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QAbstractTableModel, QModelIndex, QTimer, QElapsedTimer, QEvent, QRectF, QPointF, QRect, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QCursor, QFont, QKeySequence, QAction, QPixmap, QPainter, QPen
from PyQt6.QtWidgets import QStyleOptionViewItem

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.perf_log import medir
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
from src.theme import tema
from config.settings import CORREOS_EXCEL_PATH, POWERBI_EXCEL_PATH, CONTACTOS_EXCEL_PATH

from src.ui.custom_table import PandasTableModel, AppTableWidget
from src.ui.ingresos_base import ModeloTablaIngresos, aplicar_estilo_tabla_lectura
from src.ui import admin_estilo
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, _Spinner
from src.ui import comercial_estilo as estilo_com
from src.ui.contactos_agregar import ContactosAddDialog
from src.services import mail_registro
from src.services import mail_service
from src.services import mail_sync_service
from src.services import contacto_correo_service
from src.services import comercial_services
from src.services import powerbi_cache_service

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False): base_path = sys._MEIPASS
    else: base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

class MultiSearchLineEdit(QLineEdit):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if text:
                # Reemplaza saltos de línea por comas para búsquedas masivas
                clean_text = text.replace('\n', ', ').replace('\r', '').replace('\t', ', ')
                clean_text = re.sub(r',\s*,', ',', clean_text).strip(', ')
                self.insert(clean_text)
            return
        super().keyPressEvent(event)

# =========================================================
# WORKER: CRUZADOR MAESTRO DE CORREOS
# =========================================================
class CorreosSyncWorker(QThread):
    log_signal = pyqtSignal(str)
    # (indice del paso, estado 'activo'|'ok'|'aviso', detalle para el usuario)
    paso_signal = pyqtSignal(int, str, str)
    preview_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.paso_actual = 0

    def _paso(self, indice, estado, detalle=""):
        self.paso_actual = indice
        self.paso_signal.emit(indice, estado, detalle)

    def run(self):
        try:
            self.log_signal.emit("[SISTEMA] Iniciando cruce maestro para generar Correos.csv...")

            self._paso(0, 'activo', "Leyendo la base de Comercial…")
            df_comercial = self.data_manager.get_comercial_df()
            if df_comercial.empty: raise Exception("La tabla Comercial está vacía. No hay camiones para cruzar.")
            self._paso(0, 'ok', f"{_miles(len(df_comercial))} camiones")

            self._paso(1, 'activo', "Revisando el CDB flota de cada camión…")
            cdb_flota = df_comercial['CDB FLOTA'].astype(str).str.strip() if 'CDB FLOTA' in df_comercial.columns else pd.Series(dtype=str)
            con_cdb_flota = int((~cdb_flota.str.upper().isin(['', '-', 'NAN', 'NONE'])).sum())
            if con_cdb_flota == 0:
                raise Exception("PruebasFM todavía no tiene CDB FLOTA. Sincroniza con RM_CONTRATOS antes de actualizar los correos.")
            self._paso(1, 'ok', f"{_miles(con_cdb_flota)} camiones con CDB flota")

            self._paso(2, 'activo', "Leyendo contactos.xlsx…")
            df_contactos = pd.DataFrame()
            if CONTACTOS_EXCEL_PATH and os.path.exists(CONTACTOS_EXCEL_PATH):
                df_contactos = pd.read_excel(CONTACTOS_EXCEL_PATH)
                self._paso(2, 'ok', f"{_miles(len(df_contactos))} contactos")
            else:
                self.log_signal.emit("[AVISO] No se encontró contactos.xlsx en las configuraciones.")
                self._paso(2, 'aviso', "No está configurado: se cruzará sin la agenda")

            self._paso(3, 'activo', "Buscando el correo de cada camión…")
            df_resultado = mail_sync_service.cruzar_correos_maestro(df_comercial, None, df_contactos)

            exitos = int((df_resultado["CORREO ELECTRÓNICO"] != "").sum())
            fallos = len(df_resultado) - exitos
            self._paso(3, 'ok', f"{_miles(exitos)} con correo · {_miles(fallos)} sin correo")

            self.log_signal.emit(f"[FINALIZADO] Cruce completado. Destinos operativos encontrados: {exitos}. Sin correo asignado: {fallos}.")
            self.preview_signal.emit(df_resultado)

        except Exception as e:
            self.error_signal.emit(f"Error fatal: {str(e)}")


def _miles(n):
    return f"{int(n):,}".replace(",", ".")


class _FilaPaso(QFrame):
    """Un paso del cruce: indicador de estado, título y detalle."""

    def __init__(self, numero, titulo, parent=None):
        super().__init__(parent)
        self.setObjectName("filaPasoSync")
        self._numero = numero
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(12)
        self._indicador = QLabel(str(numero))
        self._indicador.setFixedSize(28, 28)
        self._indicador.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner = _Spinner(self, tamano=24)
        self._spinner.hide()
        textos = QVBoxLayout()
        textos.setSpacing(1)
        self._titulo = QLabel(titulo)
        self._detalle = QLabel("En espera")
        self._detalle.setWordWrap(True)
        textos.addWidget(self._titulo)
        textos.addWidget(self._detalle)
        lay.addWidget(self._indicador)
        lay.addWidget(self._spinner)
        lay.addLayout(textos, stretch=1)
        self.set_estado('espera')

    def set_estado(self, estado, detalle=None):
        if detalle is not None:
            self._detalle.setText(detalle)
        colores = {
            'espera': (estilo_com.LINEA_SUAVE, estilo_com.APAGADO, estilo_com.SUPERFICIE, estilo_com.LINEA),
            'activo': (estilo_com.PRIMARIO_SUAVE, estilo_com.PRIMARIO, estilo_com.PRIMARIO_SUAVE, estilo_com.PRIMARIO),
            'ok': (estilo_com.mezclar_con_blanco(estilo_com.VERDE, 0.14), estilo_com.VERDE, estilo_com.SUPERFICIE, estilo_com.LINEA),
            'aviso': (estilo_com.mezclar_con_blanco(estilo_com.AMBAR, 0.16), estilo_com.AMBAR, estilo_com.SUPERFICIE, estilo_com.LINEA),
            'error': (estilo_com.ROJO_SUAVE, estilo_com.ROJO, estilo_com.ROJO_SUAVE, estilo_com.ROJO),
        }
        fondo_ind, color, fondo, borde = colores[estado]
        self.setStyleSheet(f"QFrame#filaPasoSync {{ background-color: {fondo}; border: 1px solid {borde}; border-radius: 12px; }}"
                           "QLabel { background: transparent; border: none; }")
        self._titulo.setStyleSheet(f"color: {estilo_com.TINTA if estado != 'espera' else estilo_com.APAGADO}; font-size: 13px; font-weight: 600;")
        self._detalle.setStyleSheet(f"color: {color if estado in ('aviso', 'error') else estilo_com.APAGADO}; font-size: 11px;")
        activo = estado == 'activo'
        self._spinner.setVisible(activo)
        self._indicador.setVisible(not activo)
        iconos = {'ok': 'fa5s.check', 'aviso': 'fa5s.exclamation', 'error': 'fa5s.times'}
        if estado in iconos:
            self._indicador.setText("")
            self._indicador.setPixmap(qta.icon(iconos[estado], color=color).pixmap(13, 13))
        else:
            self._indicador.setPixmap(QPixmap())
            self._indicador.setText(str(self._numero))
        self._indicador.setStyleSheet(f"background-color: {fondo_ind}; color: {color}; border-radius: 14px; font-weight: 800; font-size: 12px;")


class SyncCorreosDialog(QDialog):
    """Actualiza Correos.csv cruzando Comercial (por CDB flota) con
    contactos.xlsx (mail_sync_service). Rediseño 01-10-2026: pasos con su
    estado, barra de progreso y cronómetro en vez de la terminal."""

    _PASOS = ("Camiones de Comercial", "CDB flota de los camiones", "Agenda de Contactos", "Cruce de correos")

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar base de correos")
        self.resize(720, 560)
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)
        self.worker = None
        self.df_para_guardar = None
        self.data_manager = data_manager
        self._reloj = QElapsedTimer()
        self._timer_reloj = QTimer(self)
        self._timer_reloj.setInterval(500)
        self._timer_reloj.timeout.connect(self._actualizar_reloj)
        self._setup_ui()
        QTimer.singleShot(200, self.start_sync)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaSyncCorreos")
        tarjeta.setStyleSheet(estilo_com.qss_tarjeta("tarjetaSyncCorreos") + "QLabel { background: transparent; border: none; }")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)

        cab = QHBoxLayout()
        cab.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(48, 48)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(qta.icon('fa5s.envelope-open-text', color=estilo_com.PRIMARIO).pixmap(20, 20))
        icono.setStyleSheet(f"background-color: {estilo_com.PRIMARIO_SUAVE}; border-radius: 24px;")
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.lbl_titulo = QLabel("Actualizando la base de correos")
        self.lbl_titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 17px; font-weight: bold;")
        lbl_sub = QLabel("Se cruzan los camiones de Comercial con la base de clientes y la agenda de Contactos "
                         "para saber a qué correo escribir por cada camión.")
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px;")
        textos.addWidget(self.lbl_titulo)
        textos.addWidget(lbl_sub)
        cab.addWidget(icono, alignment=Qt.AlignmentFlag.AlignTop)
        cab.addLayout(textos, stretch=1)
        lay.addLayout(cab)

        self._filas = [_FilaPaso(i + 1, t) for i, t in enumerate(self._PASOS)]
        for fila in self._filas:
            lay.addWidget(fila)

        fila_progreso = QHBoxLayout()
        self.barra = estilo_com.BarraKpi()
        self.lbl_reloj = QLabel("Preparando…")
        self.lbl_reloj.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; font-weight: 600;")
        fila_progreso.addWidget(self.barra, stretch=1)
        fila_progreso.addSpacing(10)
        fila_progreso.addWidget(self.lbl_reloj)
        lay.addLayout(fila_progreso)

        # Resultado (se muestra al terminar)
        self.panel_resultado = QWidget()
        lay_res = QHBoxLayout(self.panel_resultado)
        lay_res.setContentsMargins(0, 0, 0, 0)
        lay_res.setSpacing(10)
        self._metricas = {}
        for clave, titulo, color in (('total', "Camiones", estilo_com.PRIMARIO),
                                     ('con', "Con correo", estilo_com.VERDE),
                                     ('sin', "Sin correo", estilo_com.ROJO)):
            caja = QFrame()
            caja.setObjectName("metricaSync")
            caja.setStyleSheet(f"QFrame#metricaSync {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
            lay_caja = QVBoxLayout(caja)
            lay_caja.setContentsMargins(14, 10, 14, 10)
            lay_caja.setSpacing(2)
            lbl_t = QLabel(titulo.upper())
            lbl_t.setStyleSheet(estilo_com.QSS_KPI_TITULO)
            lbl_v = QLabel("0")
            lbl_v.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 800;")
            lay_caja.addWidget(lbl_t)
            lay_caja.addWidget(lbl_v)
            self._metricas[clave] = lbl_v
            lay_res.addWidget(caja)
        self.panel_resultado.hide()
        lay.addWidget(self.panel_resultado)

        self.btn_preview = QPushButton(" Ver vista previa de Correos.csv")
        self.btn_preview.setIcon(qta.icon('fa5s.table', color=estilo_com.TINTA))
        self.btn_preview.setCheckable(True)
        self.btn_preview.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        estilo_com.aplicar_estilo_boton_barra(self.btn_preview)
        self.btn_preview.toggled.connect(self._alternar_preview)
        self.btn_preview.hide()
        lay.addWidget(self.btn_preview, alignment=Qt.AlignmentFlag.AlignLeft)

        main_layout.addWidget(tarjeta)

        self.preview_table = AppTableWidget()
        self.preview_model = PandasTableModel()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.hide()
        main_layout.addWidget(self.preview_table, stretch=1)
        main_layout.addStretch()

        btn_layout = QHBoxLayout()
        self.lbl_estado_pie = QLabel("")
        self.lbl_estado_pie.setWordWrap(True)
        self.lbl_estado_pie.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px;")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_cancel.setMinimumWidth(110)
        ThemeManager.apply_secondary_button(self.btn_cancel)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_start = QPushButton(" Reintentar")
        self.btn_start.setIcon(qta.icon('fa5s.redo', color='white'))
        self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ThemeManager.apply_primary_button(self.btn_start)
        self.btn_start.clicked.connect(self.start_sync)
        self.btn_start.hide()

        self.btn_inject = QPushButton(" Guardar Correos.csv")
        self.btn_inject.setIcon(qta.icon('fa5s.save', color='white'))
        self.btn_inject.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ThemeManager.apply_primary_button(self.btn_inject)
        self.btn_inject.clicked.connect(self.save_data)
        self.btn_inject.hide()

        btn_layout.addWidget(self.lbl_estado_pie, stretch=1)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_inject)
        main_layout.addLayout(btn_layout)

    def _actualizar_reloj(self):
        seg = self._reloj.elapsed() // 1000
        self.lbl_reloj.setText(f"Trabajando · {seg // 60}:{seg % 60:02d}")

    def write_log(self, text):
        # El detalle técnico va a la consola; el usuario ve los pasos
        print(f"[Sync Correos] {text}")

    def _on_paso(self, indice, estado, detalle):
        if 0 <= indice < len(self._filas):
            self._filas[indice].set_estado(estado, detalle)
        completados = indice + (1 if estado in ('ok', 'aviso') else 0.5)
        self.barra.set_valor(completados / len(self._filas), estilo_com.PRIMARIO)

    def start_sync(self):
        if not CORREOS_EXCEL_PATH:
            QMessageBox.critical(self, "Error", "La ruta de Correos.csv está en blanco.\nPor favor, asígnala en la pestaña Configuración antes de continuar.")
            self.close()
            return
        if self.worker is not None and self.worker.isRunning():
            return

        for fila in self._filas:
            fila.set_estado('espera', "En espera")
        self.barra.set_valor(0, estilo_com.PRIMARIO)
        self.lbl_titulo.setText("Actualizando la base de correos")
        self.lbl_estado_pie.setText("Puede tardar hasta un minuto si las bases son grandes. No cierres la aplicación.")
        self.panel_resultado.hide()
        self.btn_preview.hide()
        self.btn_start.hide()
        self.btn_inject.hide()
        self._reloj.start()
        self._actualizar_reloj()
        self._timer_reloj.start()

        self.worker = CorreosSyncWorker(self.data_manager)
        self.worker.log_signal.connect(self.write_log)
        self.worker.paso_signal.connect(self._on_paso)
        self.worker.preview_signal.connect(self.show_preview)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.start()

    def _terminar_reloj(self, texto):
        self._timer_reloj.stop()
        seg = self._reloj.elapsed() // 1000
        self.lbl_reloj.setText(f"{texto} en {seg // 60}:{seg % 60:02d}")

    def show_preview(self, df_resultado):
        self.df_para_guardar = df_resultado
        self.preview_model.set_data(df_resultado)
        self._terminar_reloj("Listo")
        self.barra.set_valor(1.0, estilo_com.VERDE)
        total = len(df_resultado)
        con = int((df_resultado["CORREO ELECTRÓNICO"] != "").sum()) if total else 0
        self._metricas['total'].setText(_miles(total))
        self._metricas['con'].setText(_miles(con))
        self._metricas['sin'].setText(_miles(total - con))
        self.panel_resultado.show()
        self.btn_preview.show()
        self.lbl_titulo.setText("Base de correos lista para guardar")
        self.lbl_estado_pie.setText("Revisa el resumen y guarda para que el Gestor de Correos use la base nueva.")
        self.btn_cancel.setText("Cancelar")
        self.btn_inject.show()

    def _alternar_preview(self, mostrar):
        self.preview_table.setVisible(mostrar)
        self.btn_preview.setText(" Ocultar vista previa" if mostrar else " Ver vista previa de Correos.csv")
        if mostrar and self.height() < 760:
            self.resize(max(self.width(), 900), 760)

    def handle_error(self, error_msg):
        self._terminar_reloj("Detenido")
        indice = self.worker.paso_actual if self.worker is not None else 0
        detalle = error_msg.replace("Error fatal: ", "")
        if 0 <= indice < len(self._filas):
            self._filas[indice].set_estado('error', detalle)
        self.barra.set_valor(self.barra._fraccion, estilo_com.ROJO)
        self.lbl_titulo.setText("No se pudo actualizar la base de correos")
        self.lbl_estado_pie.setText("Revisa el paso marcado en rojo y vuelve a intentar.")
        self.btn_start.show()

    def save_data(self):
        velo = mostrar_guardando(self, "Guardando Correos.csv…")
        velo.repaint()
        QApplication.processEvents()
        ok, mensaje = mail_sync_service.guardar_correos_excel(self.df_para_guardar, CORREOS_EXCEL_PATH)
        if ok:
            terminar_guardando(self, texto_exito="Correos.csv guardado")
            self.accept()
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", mensaje)

    def reject(self):
        # Si el cruce sigue corriendo, el hilo se deja terminar solo (destruir
        # un QThread en marcha cierra la aplicación)
        if self.worker is not None and self.worker.isRunning():
            for senal in (self.worker.log_signal, self.worker.paso_signal, self.worker.preview_signal, self.worker.error_signal):
                try:
                    senal.disconnect()
                except TypeError:
                    pass
            self.worker.setParent(self.parent())
            self.worker.finished.connect(self.worker.deleteLater)
        self._timer_reloj.stop()
        super().reject()

# =========================================================
# MOTOR DE ENVÍO DE CORREOS VÍA OUTLOOK
# =========================================================
def _crear_sink_cierre(estado):
    """Clase de eventos que marca estado['cerrado'] cuando se cierra la ventana
    del correo (enviado o descartado). El evento Close de Outlook recibe el
    argumento Cancel; sin él el manejador falla en silencio y nunca avanza."""
    class _MailItemEventSink:
        def OnSend(self, Cancel=None):
            estado['enviado'] = True

        def OnClose(self, Cancel=None):
            estado['cerrado'] = True
    return _MailItemEventSink


class OutlookSenderThread(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(int, int, bool)  # (exitos, fallos, registro_historial_ok)
    registrado_signal = pyqtSignal()  # un correo quedó anotado en el historial

    def __init__(self, destinatarios, cc, plantilla, asunto, mensaje_base):
        super().__init__()
        self.destinatarios = destinatarios
        self.cc = cc
        self.plantilla = plantilla
        self.asunto = asunto
        self.mensaje_base = mensaje_base
        self.assets_dir = get_resource_path(os.path.join('src', 'assets'))

    def _adjuntar_cid(self, mail, filename, cid):
        path = os.path.join(self.assets_dir, filename)
        if os.path.exists(path):
            adj = mail.Attachments.Add(path)
            adj.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", cid)
        else:
            print(f"No se encontró la imagen: {path}")

    def run(self):
        pythoncom.CoInitialize()
        exitos, fallos = 0, 0
        registro_ok = True
        id_envio = datetime.now().strftime("ENV-%Y%m%d-%H%M%S")
        outlook_cerrado = False

        try:
            outlook = win32com.client.Dispatch('outlook.application')
            for idx, dest in enumerate(self.destinatarios):
                if outlook_cerrado:
                    fallos += 1
                    continue
                try:
                    self.progress_signal.emit(idx, f"Preparando correo para: {dest['correo']}...")

                    estado_cierre = {'cerrado': False, 'enviado': False}
                    try:
                        mail = win32com.client.DispatchWithEvents(outlook.CreateItem(0), _crear_sink_cierre(estado_cierre))
                        con_eventos = True
                    except Exception:
                        mail = outlook.CreateItem(0)
                        con_eventos = False

                    mail.To = dest['correo']
                    if self.cc: mail.CC = self.cc

                    # Forzamos a Outlook a resolver (verificar y subrayar) los correos instantáneamente
                    try:
                        mail.Recipients.ResolveAll()
                    except Exception:
                        pass

                    mail.Subject = self.asunto

                    if self.plantilla == "Personalizado":
                        msg = self.mensaje_base.replace('@FLOTA', str(dest['flota'])).replace('@NOMBRE', str(dest['nombre']).split(' ')[0])
                        mail.HTMLBody = msg.replace('\n', '<br>')
                    else:
                        config_plantilla = mail_service.obtener_configuracion_plantilla(self.plantilla)
                        if config_plantilla:
                            mail.HTMLBody = config_plantilla['constructor'](dest)
                            for filename, cid in config_plantilla['imagenes']:
                                self._adjuntar_cid(mail, filename, cid)

                    mail.Display()
                    exitos += 1

                    # Se espera a que el usuario envíe o cierre esta ventana
                    # antes de abrir la del siguiente destinatario, en vez de
                    # abrir todas las ventanas de Outlook de una sola vez.
                    resultado = "ENVIADO A OUTLOOK"
                    if con_eventos:
                        self.progress_signal.emit(idx, f"Esperando que envíes o cierres el correo de: {dest['correo']}...")
                        sondeo = 0
                        while not estado_cierre['cerrado']:
                            pythoncom.PumpWaitingMessages()
                            time.sleep(0.15)
                            sondeo += 1
                            # Si se cierra Outlook completo, el evento OnClose nunca llega
                            if sondeo % 7 == 0 and not self._outlook_activo(outlook):
                                outlook_cerrado = True
                                break
                        else:
                            resultado = "ENVIADO" if estado_cierre['enviado'] else "CERRADO SIN ENVIAR"

                    # El historial es append-only: se anota una sola vez, con el desenlace conocido
                    chasis_str = ", ".join(dest['chasis_list']) if dest['chasis_list'] else ""
                    registro_ok &= mail_registro.registrar_envios([mail_registro.construir_registro(
                        id_envio=id_envio, fecha_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        tipo_correo=self.plantilla.upper(),
                        razon_social=dest['flota'], chasis=chasis_str, destinatario=dest['correo'],
                        estado=resultado, asunto=self.asunto
                    )])
                    self.registrado_signal.emit()

                except Exception as e:
                    fallos += 1
                    print(f"Error al armar correo para {dest['correo']}: {e}")
                    
        except Exception as e:
            fallos = len(self.destinatarios)
            print(f"Error crítico conectando con Outlook: {e}")
        finally:
            pythoncom.CoUninitialize()

        self.finished_signal.emit(exitos, fallos, registro_ok)

    @staticmethod
    def _outlook_activo(outlook):
        try:
            outlook.Version
            return True
        except Exception:
            return False

class BorradorEjecutivoThread(QThread):
    """Abre en Outlook un borrador por cada (correo, asunto, html) sin
    enviarlo. No se anota en el historial de envíos: ese historial mide el
    contacto con clientes y un aviso interno lo distorsionaría."""
    finished_signal = pyqtSignal(int, int)  # (abiertos, fallidos)

    def __init__(self, borradores):
        super().__init__()
        self.borradores = borradores

    def run(self):
        pythoncom.CoInitialize()
        abiertos, fallidos = 0, 0
        try:
            outlook = win32com.client.Dispatch('outlook.application')
            for correo, asunto, html in self.borradores:
                try:
                    mail = outlook.CreateItem(0)
                    mail.To = correo
                    mail.Subject = asunto
                    mail.HTMLBody = html
                    mail.Display()
                    abiertos += 1
                except Exception as e:
                    fallidos += 1
                    print(f"Error al abrir el borrador para {correo}: {e}")
        except Exception as e:
            fallidos = len(self.borradores)
            print(f"Error crítico conectando con Outlook: {e}")
        finally:
            pythoncom.CoUninitialize()
        self.finished_signal.emit(abiertos, fallidos)


# =========================================================
# REGISTRO DE ENVÍOS (consulta de mail_registro.leer_historial)
# =========================================================
class RegistroEnviosDialog(QDialog):
    """Historial de envíos: una fila por envío y, al hacer clic, un panel
    flotante con su detalle (destinatarios y chasis de a 5, con "+N más")."""
    _COLUMNAS_VISTA = ["FECHA Y HORA", "TIPO DE CORREO", "FLOTA VC", "DESTINATARIOS", "UNIDADES", "ESTADO"]
    _ANCHOS = {"FECHA Y HORA": 140, "TIPO DE CORREO": 180, "FLOTA VC": 300, "DESTINATARIOS": 130, "UNIDADES": 110, "ESTADO": 170}
    _MAX_ITEMS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registro de Envíos de Correos")
        self.resize(1100, 600)
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)

        self.df_registro = pd.DataFrame()
        self._df_vista = pd.DataFrame()
        self._fila_abierta = -1
        self._expandido = {'dest': False, 'chasis': False}
        self._panel_abierto = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por destinatario, razón social, asunto...")
        self.search_input.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.18);"
            " border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; }"
            "QLineEdit:focus { border: 1px solid rgba(255,255,255,0.55); }")
        self.search_input.addAction(qta.icon('fa5s.search', color='#B8C2D6'), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.textChanged.connect(self._filtrar)

        self.btn_actualizar = QPushButton(" Actualizar")
        self.btn_actualizar.setIcon(ThemeManager.icon('fa5s.sync-alt', color='white'))
        self.btn_actualizar.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_actualizar.clicked.connect(self._cargar_registro)

        barra = admin_estilo.barra_opciones('fa5s.history', "", "", mostrar_titulo=False)
        barra.zona_filtros.addWidget(self.search_input, 1)
        barra.lay_capsula.addWidget(self.btn_actualizar)
        estilo_com.preparar_boton_capsula(self.btn_actualizar)
        layout.addWidget(barra.marco)

        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_conteo.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px; background: transparent; border: none;")
        lbl_ayuda = QLabel("Clic en una fila para ver el detalle del envío")
        lbl_ayuda.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(4, 0, 4, 0)
        fila_estado.addWidget(self.lbl_conteo)
        fila_estado.addStretch()
        fila_estado.addWidget(lbl_ayuda)
        layout.addLayout(fila_estado)

        self.model = ModeloTablaIngresos(resolver=self._resolver_color_estado,
                                         alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table = AppTableWidget()
        aplicar_estilo_tabla_lectura(self.table, 48)
        self.table.set_model_and_delegate(self.model)
        self._delegado = estilo_com.DelegadoCeldasComercial([self.table, self.table.frozen_view])
        self.table.setItemDelegate(self._delegado)
        self.table.frozen_view.setItemDelegate(self._delegado)
        self.table.clicked.connect(self._on_fila_clic)
        tarjeta, lay_tarjeta = admin_estilo.tarjeta_contenido("tarjetaRegistroEnvios")
        lay_tarjeta.addWidget(self.table, 1)
        layout.addWidget(tarjeta, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_cerrar = QPushButton("Cerrar")
        ThemeManager.apply_secondary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.accept)
        footer.addWidget(self.btn_cerrar)
        layout.addLayout(footer)

        self._panel = self._construir_panel()
        self._panel.setParent(self)
        estilo_com.crear_sombra_panel(self._panel)
        self._panel.hide()
        self._anim = QPropertyAnimation(self._panel, b"pos", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_terminada)
        self._anim.valueChanged.connect(lambda _v: estilo_com.sombra_segun_posicion(
            self._panel, self._geometria_panel(False).x(), self._geometria_panel(True).x()))

        self._cargar_registro()

    @staticmethod
    def _resolver_color_estado(columna, valor, es_fondo):
        if columna != "ESTADO":
            return None
        texto = str(valor).lower()
        if texto == "enviado":
            return "#DDF4EB" if es_fondo else estilo_com.VERDE
        if texto.startswith("cerrado"):
            return estilo_com.ROJO_SUAVE if es_fondo else estilo_com.ROJO
        return None

    # --- Datos ---
    def _cargar_registro(self):
        self.df_registro = mail_registro.leer_historial()
        self._cerrar_panel()
        self._filtrar(self.search_input.text())

    @staticmethod
    def _partir(texto, separador):
        return [p.strip() for p in str(texto or "").replace(";", ",").split(",") if p.strip()] if separador else []

    def _filtrar(self, texto):
        df = self.df_registro.copy()
        texto = texto.strip().lower()
        if texto and not df.empty:
            mask = pd.Series(False, index=df.index)
            for col in df.columns:
                mask |= df[col].astype(str).str.lower().str.contains(texto, na=False, regex=False)
            df = df[mask]
        if not df.empty:
            df = df.iloc[::-1]
        self._df_vista = df.reset_index(drop=True)
        self._cerrar_panel()

        def col(nombre):
            return self._df_vista[nombre].astype(str) if nombre in self._df_vista.columns else pd.Series([""] * len(self._df_vista))
        n_dest = col('destinatario').map(lambda t: len(self._partir(t, True)))
        n_uni = col('chasis').map(lambda t: len(self._partir(t, True)))
        vista = pd.DataFrame({
            "FECHA Y HORA": col('fecha_hora'),
            "TIPO DE CORREO": col('tipo_correo').str.capitalize(),
            "FLOTA VC": col('razon_social'),
            "DESTINATARIOS": [f"{n} correo{'s' if n != 1 else ''}" for n in n_dest],
            "UNIDADES": [f"{n} unidad{'es' if n != 1 else ''}" for n in n_uni],
            "ESTADO": col('estado').str.capitalize(),
        })
        self.model.set_data(vista)
        for i, nombre in enumerate(vista.columns):
            self.table.setColumnWidth(i, self._ANCHOS.get(nombre, 140))
        n = len(vista)
        self.lbl_conteo.setText(f"<span style='color:{estilo_com.PRIMARIO}; font-weight:700'>{n}</span> envío{'s' if n != 1 else ''}")

    # --- Panel de detalle ---
    def _construir_panel(self):
        panel = QFrame()
        panel.setObjectName("panelDetalleEnvio")
        panel.setFixedWidth(390)
        panel.setStyleSheet(f"QFrame#panelDetalleEnvio {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid #D5DDEA; border-radius: 14px; }}")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QFrame()
        cab.setObjectName("cabDetalleEnvio")
        cab.setStyleSheet(f"QFrame#cabDetalleEnvio {{ background: transparent; border: none; border-bottom: 1px solid {estilo_com.LINEA}; }}")
        lay_cab = QHBoxLayout(cab)
        lay_cab.setContentsMargins(16, 14, 12, 12)
        lay_cab.setSpacing(12)
        self._lbl_avatar = QLabel()
        self._lbl_avatar.setFixedSize(42, 42)
        self._lbl_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_avatar.setStyleSheet(f"background: {estilo_com.PRIMARIO_SUAVE}; color: {estilo_com.PRIMARIO}; border-radius: 12px; font-weight: 800; font-size: 14px;")
        bloque = QVBoxLayout()
        bloque.setSpacing(2)
        self._lbl_razon = QLabel()
        self._lbl_razon.setWordWrap(True)
        self._lbl_razon.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 14px; font-weight: bold; background: transparent; border: none;")
        self._lbl_fecha = QLabel()
        self._lbl_fecha.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        bloque.addWidget(self._lbl_razon)
        bloque.addWidget(self._lbl_fecha)
        btn_x = QPushButton()
        btn_x.setIcon(qta.icon('fa5s.times', color=estilo_com.APAGADO))
        btn_x.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 8px; }"
                            f"QPushButton:hover {{ background: {estilo_com.SUPERFICIE_2}; }}")
        btn_x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_x.setFixedSize(28, 28)
        btn_x.setToolTip("Cerrar detalle")
        btn_x.clicked.connect(self._cerrar_panel)
        lay_cab.addWidget(self._lbl_avatar, 0, Qt.AlignmentFlag.AlignTop)
        lay_cab.addLayout(bloque, 1)
        lay_cab.addWidget(btn_x, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(cab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("QWidget { background: transparent; }")
        self._lay_cuerpo = QVBoxLayout(cuerpo)
        self._lay_cuerpo.setContentsMargins(16, 14, 16, 14)
        self._lay_cuerpo.setSpacing(14)
        scroll.setWidget(cuerpo)
        lay.addWidget(scroll, 1)
        return panel

    def _titulo_seccion(self, texto):
        lbl = QLabel(texto.upper())
        lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; font-weight: bold; letter-spacing: 1px; background: transparent; border: none;")
        return lbl

    def _caja_texto(self, texto):
        lbl = QLabel(texto)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 9px; padding: 7px 10px;")
        return lbl

    def _boton_mas(self, clave, restantes, expandido):
        btn = QPushButton(" Mostrar menos" if expandido else f" +{restantes} más")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(f"QPushButton {{ color: {estilo_com.PRIMARIO}; font-weight: bold; font-size: 12px; background: transparent; border: none; text-align: left; padding: 2px 2px; }}"
                          f"QPushButton:hover {{ text-decoration: underline; }}")
        btn.clicked.connect(lambda _c=False: self._alternar(clave))
        return btn

    def _alternar(self, clave):
        self._expandido[clave] = not self._expandido[clave]
        self._pintar_detalle()

    def _pintar_detalle(self):
        while self._lay_cuerpo.count():
            w = self._lay_cuerpo.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        r = self._df_vista.iloc[self._fila_abierta]

        def valor(n):
            return str(r[n]) if n in r.index and pd.notna(r[n]) else ""
        razon = valor('razon_social')
        self._lbl_razon.setText(razon)
        self._lbl_avatar.setText("".join(p[0] for p in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", razon)[:2]).upper() or "?")
        self._lbl_fecha.setText(valor('fecha_hora'))

        fila = QHBoxLayout()
        fila.setSpacing(8)
        for titulo, texto in (("Tipo de correo", valor('tipo_correo').capitalize()), ("Estado", valor('estado').capitalize())):
            celda = QFrame()
            celda.setStyleSheet(f"QFrame {{ border: 1px solid {estilo_com.LINEA}; border-radius: 10px; background: transparent; }} QLabel {{ border: none; }}")
            lc = QVBoxLayout(celda)
            lc.setContentsMargins(10, 7, 10, 7)
            lc.setSpacing(0)
            t = QLabel(titulo)
            t.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px;")
            v = QLabel(texto)
            v.setWordWrap(True)
            v.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; font-weight: bold;")
            lc.addWidget(t)
            lc.addWidget(v)
            fila.addWidget(celda, 1)
        contenedor = QWidget()
        contenedor.setLayout(fila)
        self._lay_cuerpo.addWidget(contenedor)

        self._lay_cuerpo.addWidget(self._titulo_seccion("Asunto"))
        self._lay_cuerpo.addWidget(self._caja_texto(valor('asunto') or "-"))

        for clave, titulo, items in (("dest", "Destinatarios", self._partir(valor('destinatario'), True)),
                                     ("chasis", "Chasis", self._partir(valor('chasis'), True))):
            self._lay_cuerpo.addWidget(self._titulo_seccion(f"{titulo} ({len(items)})"))
            if not items:
                self._lay_cuerpo.addWidget(self._caja_texto("Sin datos"))
                continue
            visibles = items if self._expandido[clave] else items[:self._MAX_ITEMS]
            if clave == "dest":
                for c in visibles:
                    self._lay_cuerpo.addWidget(self._caja_texto(c))
            else:
                chips = QLabel("  ".join(f"<span style='background:{estilo_com.SUPERFICIE_2}'>&nbsp;{c}&nbsp;</span>" for c in visibles))
                chips.setTextFormat(Qt.TextFormat.RichText)
                chips.setWordWrap(True)
                chips.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; background: transparent; border: none;")
                self._lay_cuerpo.addWidget(chips)
            if len(items) > self._MAX_ITEMS:
                self._lay_cuerpo.addWidget(self._boton_mas(clave, len(items) - self._MAX_ITEMS, self._expandido[clave]))

        self._lay_cuerpo.addWidget(self._titulo_seccion("Id de envío"))
        lbl_id = QLabel(valor('id_envio') or "-")
        lbl_id.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px; background: transparent; border: none;")
        lbl_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lay_cuerpo.addWidget(lbl_id)
        self._lay_cuerpo.addStretch()

    def _on_fila_clic(self, index):
        if not index.isValid() or not (0 <= index.row() < len(self._df_vista)):
            return
        self._fila_abierta = index.row()
        self._expandido = {'dest': False, 'chasis': False}
        self._pintar_detalle()
        self._mostrar_panel(True)

    def _cerrar_panel(self):
        self._fila_abierta = -1
        if hasattr(self, '_panel'):
            self._mostrar_panel(False)

    def _geometria_panel(self, abierto):
        ancho, margen = 390, 16
        x = self.width() - margen - ancho if abierto else self.width() + 30
        return QRect(x, margen, ancho, max(0, self.height() - 2 * margen))

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim.stop()
        if mostrar:
            if not self._panel.isVisible():
                self._panel.setGeometry(self._geometria_panel(False))
                self._panel.show()
            self._panel.raise_()
        self._anim.setStartValue(self._panel.pos())
        self._anim.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim.start()

    def _on_anim_terminada(self):
        if not self._panel_abierto:
            self._panel.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = self.__dict__.get('_panel')
        if panel is not None and panel.isVisible():
            self._anim.stop()
            panel.setGeometry(self._geometria_panel(self._panel_abierto))


# =========================================================
# MODELO DE LA TABLA PRINCIPAL DE MailDialog
# =========================================================
def mascara_por_vencer(df):
    """Contratos con FECHA TERMINO entre hoy y 30 días más (sin los mensuales)."""
    if df.empty or 'FECHA TERMINO' not in df.columns:
        return pd.Series(False, index=df.index)
    hoy = pd.Timestamp(datetime.now().date())
    fechas = pd.to_datetime(df['FECHA TERMINO'], format='%d-%m-%Y', errors='coerce')
    mensual = df['FECHA TERMINO'].astype(str).str.upper() == 'MENSUAL'
    dias = (fechas - hoy).dt.days
    return (~mensual) & (dias >= 0) & (dias <= 30)


def mascara_sin_correo(df):
    if df.empty or 'CORREO ELECTRÓNICO' not in df.columns:
        return pd.Series(True, index=df.index)
    return df['CORREO ELECTRÓNICO'].astype(str).str.strip() == ""


class ModeloCorreosAgrupado(ModeloTablaIngresos):
    """Tabla del Gestor de Correos en dos fases: una fila por cliente (razón
    social) o, con un cliente abierto, una fila por unidad. La primera columna
    es la casilla: el estado sale de los VIN marcados (`checked_vins`, el mismo
    set de MailDialog) de la fila, y marcar una fila de cliente marca todos sus
    VIN. `vins_de_clave` devuelve los VIN de la fila a partir de su clave
    (razón social o VIN), así el orden de la tabla puede cambiar sin perderlos."""

    def __init__(self, checked_vins, vins_de_clave, **kwargs):
        super().__init__(**kwargs)
        self._checked_vins = checked_vins
        self._vins_de_clave = vins_de_clave
        self._columna_clave = None

    def set_vista(self, df, columna_clave):
        self._columna_clave = columna_clave
        self.set_data(df)

    def clave_de_fila(self, fila):
        if self._columna_clave is None or not (0 <= fila < len(self._df)):
            return ""
        return str(self._df.at[self._df.index[fila], self._columna_clave])

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and index.column() == 0:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                vins = self._vins_de_clave(self.clave_de_fila(index.row()))
                marcados = sum(1 for v in vins if v in self._checked_vins)
                if marcados == 0:
                    return Qt.CheckState.Unchecked
                return Qt.CheckState.Checked if marcados == len(vins) else Qt.CheckState.PartiallyChecked
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return None
        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        vins = self._vins_de_clave(self.clave_de_fila(index.row()))
        if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, 2):
            self._checked_vins.update(vins)
        else:
            self._checked_vins.difference_update(vins)
        self.dataChanged.emit(index, index, [role])
        return True


class _DelegadoCasilla(estilo_com.DelegadoCeldasComercial):
    """Igual que el de Comercial, con una casilla dibujada (marcada, a medias o
    vacía) en la primera columna; un clic en cualquier parte de esa celda la alterna."""

    LADO = 16

    def __init__(self, vistas):
        super().__init__(vistas)
        self._dibujando = False

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if self._dibujando:
            option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator

    def paint(self, painter, option, index):
        estado = index.data(Qt.ItemDataRole.CheckStateRole) if index.column() == 0 else None
        if estado is None:
            return super().paint(painter, option, index)
        self._dibujando = True
        try:
            super().paint(painter, option, index)
        finally:
            self._dibujando = False
        centro = option.rect.center()
        caja = QRectF(centro.x() - self.LADO / 2 + 0.5, centro.y() - self.LADO / 2 + 0.5, self.LADO, self.LADO)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if estado == Qt.CheckState.Unchecked:
            painter.setPen(QPen(QColor(tema.fondo("#A9B3C4")), 1.5))
            painter.setBrush(QColor(tema.fondo(estilo_com.SUPERFICIE)))
            painter.drawRoundedRect(caja, 4, 4)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(estilo_com.PRIMARIO))
            painter.drawRoundedRect(caja, 4, 4)
            painter.setPen(QPen(QColor("white"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x0, y0 = caja.left(), caja.top()
            if estado == Qt.CheckState.Checked:
                painter.drawPolyline([QPointF(x0 + 4, y0 + 8.5), QPointF(x0 + 7, y0 + 11.5), QPointF(x0 + 12, y0 + 5)])
            else:
                painter.drawLine(QPointF(x0 + 4, y0 + 8), QPointF(x0 + 12, y0 + 8))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if (index.column() == 0 and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton and option.rect.contains(event.position().toPoint())
                and index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            actual = index.data(Qt.ItemDataRole.CheckStateRole)
            model.setData(index, Qt.CheckState.Unchecked if actual == Qt.CheckState.Checked else Qt.CheckState.Checked,
                          Qt.ItemDataRole.CheckStateRole)
            return True
        return super().editorEvent(event, model, option, index)


# =========================================================
# LA VENTANA MODERNA DE CORREOS
# =========================================================
class MailDialog(QDialog):
    def __init__(self, parent=None, vins_preseleccionados=None, plantilla_inicial=None):
        super().__init__(parent)
        self.setWindowTitle("Gestor de Correos - Gestor SSCC")
        self.resize(1280, 760)
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)

        self.data_manager = DataManager()
        self.df_correos = pd.DataFrame()
        self.df_display = pd.DataFrame()
        self.current_kpi = "total"
        self.checked_vins = set()  # Mochila de memoria para checkboxes
        self._all_checked = False  # Estado del Check Global
        self._vin_cdb_map = {}  # VIN -> CDB, ver _build_vin_to_cdb_map()
        self._grupo_abierto = None  # razón social abierta en la fase 2
        self._vins_por_clave = {}

        self._setup_ui()
        self._load_correos_file()

        # Entrada desde Gestionar CM (comercial.py): preseleccionar VIN y
        # plantilla es opcional y no cambia el comportamiento por defecto
        # (MailDialog() / MailDialog(parent=...) siguen igual).
        if vins_preseleccionados:
            self._preseleccionar_vins(vins_preseleccionados)
        if plantilla_inicial:
            self.combo_plantilla.setCurrentText(plantilla_inicial)

    def _load_correos_file(self):
        if os.path.exists(CORREOS_EXCEL_PATH):
            try:
                # Instrumentacion temporal (auditoria de rendimiento B-5,
                # 18-09-2026): separa lectura del CSV (B-5.2, antes Correos.xlsx
                # via openpyxl), construccion del mapa VIN->CDB y primer render
                # (via _populate_table). No cambia el comportamiento.
                # dtype=str + keep_default_na=False: mismo patron que LogApp.csv/
                # CasosBajaCM.csv en el resto del proyecto, para que VIN/CDB/RUT
                # no pierdan ceros iniciales ni pandas les infiera un tipo numerico.
                with medir("B-5 MailDialog > read_csv(Correos.csv)"):
                    self.df_correos = pd.read_csv(CORREOS_EXCEL_PATH, dtype=str, keep_default_na=False)
                print(f"[PERF][UI] B-5 MailDialog -> {len(self.df_correos)} filas leidas de Correos.csv")
                with medir("B-5 MailDialog > _build_vin_to_cdb_map"):
                    self._vin_cdb_map = self._build_vin_to_cdb_map()

                # Poblar combo de planes dinámicamente según la data viva
                if 'TIPO DE SERVICIO' in self.df_correos.columns:
                    planes = sorted([str(p).strip().upper() for p in self.df_correos['TIPO DE SERVICIO'].unique() if str(p).strip() != ''])
                    self.combo_plan.blockSignals(True)
                    self.combo_plan.clear()
                    self.combo_plan.addItem("Todos los Planes")
                    self.combo_plan.addItems(planes)
                    self.combo_plan.blockSignals(False)

                self._populate_table()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo leer Correos.csv:\n{e}")

    def _build_vin_to_cdb_map(self):
        """Correos.csv no tiene columna CDB (se descarta al generarse en
        mail_sync_service.cruzar_correos_maestro). Se resuelve por VIN
        contra Comercial (misma normalización de CDB usada ahí), una sola
        vez por carga, para no recalcularlo en cada keystroke de búsqueda."""
        from src.services.comercial_services import contratos_actuales
        df_comercial = contratos_actuales(self.data_manager.get_comercial_df())
        if df_comercial.empty or 'VIN' not in df_comercial.columns or 'CDB FLOTA' not in df_comercial.columns:
            return {}
        vins = df_comercial['VIN'].astype(str).str.strip()
        cdbs = df_comercial['CDB FLOTA'].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\s+', '', regex=True).str.upper()
        return dict(zip(vins, cdbs))

    def _preseleccionar_vins(self, vins):
        """Prefiltra la tabla con los VIN dados (reutiliza el buscador
        multi-termino existente en el search_bar, sin reimplementar
        busqueda) y marca sus checkboxes. Comparacion insensible a
        mayusculas: Correos.csv conserva el casing original de Comercial,
        que puede no coincidir con el de la seleccion en Gestionar CM."""
        vins_texto = [str(v).strip() for v in vins if str(v).strip()]
        vins_normalizados = {v.upper() for v in vins_texto}
        if not vins_normalizados:
            return

        # setText dispara _populate_table de forma sincrona (misma
        # conexion que usa la busqueda manual), dejando self.df_display ya
        # filtrado antes de continuar.
        self.search_bar.setText(", ".join(vins_texto))

        if not self.df_display.empty and 'VIN' in self.df_display.columns:
            for vin_real in self.df_display['VIN'].astype(str):
                if vin_real.strip().upper() in vins_normalizados:
                    self.checked_vins.add(vin_real)

        # Con un solo cliente se abre directo en sus unidades, donde aparece el panel de redacción
        if not self.df_display.empty:
            claves = self._serie_clave(self.df_display).unique()
            if len(claves) == 1:
                self._grupo_abierto = claves[0]

        self._render_table()

    # Bandejas del selector superior, en el mismo orden que sus botones
    _BANDEJAS = ("total", "xvencer", "sincorreo", "concorreo")
    _PLANTILLAS = ["Personalizado (Escribir desde cero)", "Bienvenida", "Crear Cuenta", "Capacitación",
                   "Activación", "Revisión Periódica", "Aviso de Vencimiento", "Cancelación"]
    _MAX_DESTINATARIOS_VISIBLES = 40

    def _setup_ui(self):
        """Rediseño 01-10-2026 con el estilo de Comercial: bandejas, KPIs,
        tabla a todo el ancho y panel de redacción a la derecha (la tabla de
        resumen pasó al panel como lista de destinatarios)."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        columna = QVBoxLayout()
        columna.setSpacing(12)

        self.btn_volver = QPushButton()
        self.btn_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color='white'))
        self.btn_volver.setToolTip("Volver a la lista de clientes")
        self.btn_volver.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_volver.setFixedWidth(44)
        self.btn_volver.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18); "
            "border-radius: 10px; min-height: 34px; } QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self.btn_volver.clicked.connect(self._cerrar_grupo)
        self.btn_volver.hide()

        self.search_bar = MultiSearchLineEdit()
        self.search_bar.setPlaceholderText("Buscar razón social, RUT o VIN. Separa varios VIN con comas o pega una lista")
        self.search_bar.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.18);"
            " border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; }"
            "QLineEdit:focus { border: 1px solid rgba(255,255,255,0.55); }")
        self.search_bar.addAction(qta.icon('fa5s.search', color='#B8C2D6'), QLineEdit.ActionPosition.LeadingPosition)
        self.search_bar.textChanged.connect(self._populate_table)

        self.combo_plan = estilo_com.ComboTarjeta("Plan")
        self.combo_plan.addItem("Todos los Planes")
        admin_estilo.combo_barra(self.combo_plan, 170)
        self.combo_plan.currentTextChanged.connect(self._populate_table)

        self.btn_sync = QPushButton(" Sincronizar BBDD Correos")
        self.btn_sync.setIcon(ThemeManager.icon('fa5s.database', color='white'))
        self.btn_sync.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_sync.clicked.connect(self._open_sync_dialog)

        self.btn_ver_registro = QPushButton(" Registro")
        self.btn_ver_registro.setIcon(ThemeManager.icon('fa5s.history', color='white'))
        self.btn_ver_registro.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_ver_registro.setToolTip("Ver registro de correos enviados")
        self.btn_ver_registro.clicked.connect(self._abrir_registro_envios)

        barra = admin_estilo.barra_opciones('fa5s.envelope', "", "", mostrar_titulo=False)
        barra.marco.layout().insertWidget(0, self.btn_volver)
        barra.zona_filtros.addWidget(self.search_bar, 1)
        barra.zona_filtros.addWidget(self.combo_plan)
        for boton in (self.btn_sync, self.btn_ver_registro):
            barra.lay_capsula.addWidget(boton)
            estilo_com.preparar_boton_capsula(boton)
        columna.addWidget(barra.marco)

        # Tarjetas KPI de Comercial: las cuatro son bandejas (filtran al hacer clic)
        contenedor_kpis, tarjetas = admin_estilo.fila_kpis(4)
        self._kpis = {}
        specs = (('total', "Contratos", estilo_com.PRIMARIO, "Todas las unidades con los filtros actuales."),
                 ('xvencer', "Por vencer", estilo_com.AMBAR, "Contratos que terminan dentro de los próximos 30 días."),
                 ('sincorreo', "Sin correo", estilo_com.ROJO, "Unidades cuya empresa no tiene un correo registrado."),
                 ('concorreo', "Con correo", estilo_com.VERDE, "Unidades cuya empresa tiene un correo registrado."))
        for tarjeta, (clave, titulo, color, ayuda) in zip(tarjetas, specs):
            tarjeta.definir(titulo, color, ayuda)
            tarjeta.setCheckable(True)
            tarjeta.setCursor(Qt.CursorShape.PointingHandCursor)
            tarjeta.clicked.connect(lambda _c=False, k=clave: self._apply_kpi_filter(k))
            self._kpis[clave] = tarjeta
        self._kpis['total'].setChecked(True)
        columna.addWidget(contenedor_kpis)

        # Estado de la tabla, separado de la tarjeta
        lbl_unidades = QLabel("Unidades")
        lbl_unidades.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 13px; font-weight: bold; background: transparent; border: none;")
        self.lbl_conteo_tabla = QLabel("")
        self.lbl_conteo_tabla.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_conteo_tabla.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px; background: transparent; border: none;")
        lbl_ayuda = QLabel("Clic en la fila para ver sus unidades · casilla para marcar · clic derecho para agregar correo")
        lbl_ayuda.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(4, 0, 4, 0)
        fila_estado.addWidget(lbl_unidades)
        fila_estado.addSpacing(8)
        fila_estado.addWidget(self.lbl_conteo_tabla)
        fila_estado.addStretch()
        fila_estado.addWidget(lbl_ayuda)
        columna.addLayout(fila_estado)

        # Misma tabla que Comercial: una fila por cliente y, al abrirlo, una por unidad
        self.model = ModeloCorreosAgrupado(
            self.checked_vins, self._vins_de_clave, resolver=self._resolver_color,
            alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model.dataChanged.connect(self._on_model_data_changed)
        self.table = AppTableWidget()
        aplicar_estilo_tabla_lectura(self.table, 44)
        self.table.set_model_and_delegate(self.model)
        self._delegado = _DelegadoCasilla([self.table, self.table.frozen_view])
        self.table.setItemDelegate(self._delegado)
        self.table.frozen_view.setItemDelegate(self._delegado)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.sort_changed.connect(self._render_table)
        self.table.clicked.connect(self._on_tabla_clic)
        self.table.customContextMenuRequested.disconnect()
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        tarjeta_tabla, lay_tabla = admin_estilo.tarjeta_contenido("tarjetaTablaCorreos")
        lay_tabla.addWidget(self.table, 1)
        columna.addWidget(tarjeta_tabla, stretch=1)

        main_layout.addLayout(columna, stretch=1)
        # Panel flotante fuera del layout (como Comercial): la tabla usa todo el
        # ancho y el panel aparece solo en la fase 2 con alguna unidad marcada
        self._panel_redaccion = self._construir_panel_redaccion()
        self._panel_redaccion.setParent(self)
        estilo_com.crear_sombra_panel(self._panel_redaccion)
        self._panel_redaccion.hide()
        self._panel_abierto = False
        self._anim_panel = QPropertyAnimation(self._panel_redaccion, b"pos", self)
        self._anim_panel.setDuration(240)
        self._anim_panel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_panel.finished.connect(self._on_anim_panel_terminada)
        self._anim_panel.valueChanged.connect(self._sombra_panel)
        self._update_summary()

    def _geometria_panel(self, abierto):
        ancho, margen = 390, 16
        x = self.width() - margen - ancho if abierto else self.width() + 30
        return QRect(x, margen, ancho, max(0, self.height() - 2 * margen))

    def _sombra_panel(self, _valor=None):
        estilo_com.sombra_segun_posicion(self._panel_redaccion, self._geometria_panel(False).x(),
                                         self._geometria_panel(True).x())

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        panel = self._panel_redaccion
        self._anim_panel.stop()
        if mostrar:
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel(False))
                panel.show()
            panel.raise_()
        self._anim_panel.setStartValue(panel.pos())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim_panel.start()

    def _on_anim_panel_terminada(self):
        if not self._panel_abierto:
            self._panel_redaccion.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = self.__dict__.get('_panel_redaccion')
        if panel is not None and panel.isVisible():
            self._anim_panel.stop()
            panel.setGeometry(self._geometria_panel(self._panel_abierto))

    def _pintar_kpi(self, clave, valor, fraccion, subtitulo):
        self._kpis[clave].actualizar(f"{valor:,}".replace(",", "."), fraccion, subtitulo)

    def _construir_panel_redaccion(self):
        panel = QFrame()
        panel.setObjectName("panelRedaccionCorreos")
        panel.setFixedWidth(390)
        panel.setStyleSheet(f"QFrame#panelRedaccionCorreos {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid #D5DDEA; border-radius: 14px; }}")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QFrame()
        cab.setObjectName("cabPanelCorreos")
        cab.setStyleSheet(f"QFrame#cabPanelCorreos {{ background: transparent; border: none; border-bottom: 1px solid {estilo_com.LINEA}; }}")
        lay_cab = QVBoxLayout(cab)
        lay_cab.setContentsMargins(18, 14, 18, 12)
        lay_cab.setSpacing(2)
        lbl_titulo = QLabel("Redactar correo")
        lbl_titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        lbl_sub = QLabel("Se abrirá un borrador de Outlook por destinatario")
        lbl_sub.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        lay_cab.addWidget(lbl_titulo)
        lay_cab.addWidget(lbl_sub)
        lay.addWidget(cab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("QWidget { background: transparent; }")
        lay_cuerpo = QVBoxLayout(cuerpo)
        lay_cuerpo.setContentsMargins(18, 14, 18, 14)
        lay_cuerpo.setSpacing(8)

        qss_input = f"""
            QLineEdit, QTextEdit {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA};
                                    border-radius: 9px; padding: 7px 10px; color: {estilo_com.TINTA}; font-size: 12px; }}
            QLineEdit:focus, QTextEdit:focus {{ border: 1px solid {estilo_com.PRIMARIO}; }}
        """

        # combo_plantilla sigue siendo la fuente de verdad (lo usa Gestionar CM
        # con setCurrentText); los botones solo lo manejan
        self.combo_plantilla = QComboBox(cuerpo)
        self.combo_plantilla.addItems(self._PLANTILLAS)
        self.combo_plantilla.hide()
        self.combo_plantilla.currentTextChanged.connect(self._on_plantilla_changed)
        self.combo_plantilla.currentIndexChanged.connect(self._marcar_boton_plantilla)

        lay_cuerpo.addWidget(self._etiqueta_panel("Plantilla"))
        grilla = QGridLayout()
        grilla.setSpacing(6)
        self._grupo_plantillas = QButtonGroup(self)
        self._grupo_plantillas.setExclusive(True)
        qss_chip = f"""
            QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 8px;
                           padding: 7px 8px; color: {estilo_com.APAGADO}; font-weight: 600; font-size: 11px; }}
            QPushButton:hover:!checked {{ color: {estilo_com.TINTA}; border: 1px solid #B9C6DA; }}
            QPushButton:checked {{ background-color: {estilo_com.PRIMARIO_SUAVE}; color: {estilo_com.PRIMARIO}; border: 1px solid {estilo_com.PRIMARIO}; }}
        """
        for i, nombre in enumerate(self._PLANTILLAS):
            btn = QPushButton("Personalizado" if "Personalizado" in nombre else nombre)
            btn.setCheckable(True)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(qss_chip)
            self._grupo_plantillas.addButton(btn, i)
            grilla.addWidget(btn, i // 2, i % 2)
        self._grupo_plantillas.idClicked.connect(self.combo_plantilla.setCurrentIndex)
        lay_cuerpo.addLayout(grilla)
        lay_cuerpo.addSpacing(6)

        lay_cuerpo.addWidget(self._etiqueta_panel("Asunto"))
        self.txt_asunto = QLineEdit()
        self.txt_asunto.setStyleSheet(qss_input + "QLineEdit { font-weight: bold; }")
        lay_cuerpo.addWidget(self.txt_asunto)

        lay_cuerpo.addWidget(self._etiqueta_panel("CC"))
        self.txt_cc = QLineEdit()
        self.txt_cc.setPlaceholderText("Opcional. Separa varios correos con ;")
        self.txt_cc.setStyleSheet(qss_input)
        lay_cuerpo.addWidget(self.txt_cc)

        lay_cuerpo.addWidget(self._etiqueta_panel("Mensaje"))
        self.txt_mensaje = QTextEdit()
        self.txt_mensaje.setMinimumHeight(130)
        self.txt_mensaje.setStyleSheet(qss_input)
        lay_cuerpo.addWidget(self.txt_mensaje)
        lay_cuerpo.addSpacing(6)

        self.lbl_titulo_destinatarios = self._etiqueta_panel("Destinatarios")
        lay_cuerpo.addWidget(self.lbl_titulo_destinatarios)
        self._lista_destinatarios = QVBoxLayout()
        self._lista_destinatarios.setSpacing(6)
        lay_cuerpo.addLayout(self._lista_destinatarios)
        lay_cuerpo.addStretch()

        scroll.setWidget(cuerpo)
        lay.addWidget(scroll, stretch=1)

        pie = QFrame()
        pie.setObjectName("piePanelCorreos")
        pie.setStyleSheet(f"QFrame#piePanelCorreos {{ background-color: {estilo_com.SUPERFICIE_2}; border: none; border-top: 1px solid {estilo_com.LINEA}; border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}")
        lay_pie = QVBoxLayout(pie)
        lay_pie.setContentsMargins(18, 12, 18, 14)
        lay_pie.setSpacing(8)
        self.lbl_aviso_sin_correo = QLabel("")
        self.lbl_aviso_sin_correo.setWordWrap(True)
        self.lbl_aviso_sin_correo.setStyleSheet(f"background-color: {estilo_com.ROJO_SUAVE}; color: {estilo_com.ROJO}; border-radius: 9px; padding: 8px 10px; font-size: 11px; font-weight: 600; border: none;")
        self.lbl_aviso_sin_correo.hide()
        self.btn_send = QPushButton(" Abrir en Outlook")
        self.btn_send.setIcon(qta.icon('fa5s.external-link-alt', color='white'))
        self.btn_send.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_send.setMinimumHeight(40)
        self.btn_send.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR + "QPushButton { min-height: 40px; font-size: 13px; }")
        self.btn_send.clicked.connect(self.enviar_correos)
        lay_pie.addWidget(self.lbl_aviso_sin_correo)
        lay_pie.addWidget(self.btn_send)
        lay.addWidget(pie)

        self._marcar_boton_plantilla(self.combo_plantilla.currentIndex())
        self._on_plantilla_changed(self.combo_plantilla.currentText())
        return panel

    def _etiqueta_panel(self, texto):
        lbl = QLabel(texto.upper())
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _marcar_boton_plantilla(self, indice):
        btn = self._grupo_plantillas.button(indice)
        if btn is not None:
            btn.setChecked(True)

    def _crear_item_destinatario(self, grupo):
        sin_correo = not grupo['correo']
        color = estilo_com.ROJO if sin_correo else estilo_com.PRIMARIO
        fondo = estilo_com.ROJO_SUAVE if sin_correo else estilo_com.PRIMARIO_SUAVE
        item = QFrame()
        item.setObjectName("itemDestinatario")
        item.setStyleSheet(f"QFrame#itemDestinatario {{ border: 1px solid {estilo_com.ROJO if sin_correo else estilo_com.LINEA}; border-radius: 10px; background-color: {estilo_com.SUPERFICIE}; }} QLabel {{ background: transparent; border: none; }}")
        lay = QHBoxLayout(item)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        avatar = QLabel(estilo_com.iniciales(grupo['flota']))
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(f"background-color: {fondo}; color: {color}; border-radius: 15px; font-weight: bold; font-size: 10px;")
        textos = QVBoxLayout()
        textos.setSpacing(0)
        lbl_flota = QLabel()
        lbl_flota.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; font-weight: 600;")
        lbl_flota.setText(lbl_flota.fontMetrics().elidedText(grupo['flota'] or "(sin razón social)", Qt.TextElideMode.ElideRight, 210))
        lbl_flota.setToolTip(grupo['flota'])
        correos = [c.strip() for c in re.split(r'[;,]', grupo['correo']) if c.strip()]
        if sin_correo or not correos:
            texto_correo = "Sin correo asignado"
        else:
            texto_correo = f"{len(correos)} correo{'s' if len(correos) != 1 else ''}"
            lbl_flota.setToolTip(grupo['flota'] + "\n" + "\n".join(correos))
        lbl_correo = QLabel(texto_correo)
        lbl_correo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl_flota.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl_correo.setStyleSheet(f"color: {estilo_com.ROJO if sin_correo else estilo_com.APAGADO}; font-size: 11px;")
        textos.addWidget(lbl_flota)
        textos.addWidget(lbl_correo)
        n = len(grupo['chasis_list'])
        lbl_n = QLabel(f"{n} VIN")
        lbl_n.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 800;")
        lay.addWidget(avatar)
        lay.addLayout(textos, stretch=1)
        lay.addWidget(lbl_n)
        return item

    def _open_sync_dialog(self):
        dialog = SyncCorreosDialog(self.data_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_correos_file()

    def _abrir_registro_envios(self):
        dialog = RegistroEnviosDialog(self)
        dialog.exec()

    def _apply_kpi_filter(self, filter_id):
        if filter_id not in self._BANDEJAS:
            filter_id = "total"
        self.current_kpi = filter_id
        for clave in self._BANDEJAS:
            self._kpis[clave].setChecked(clave == filter_id)
        self._grupo_abierto = None
        self._populate_table()

    # --- CLIC EN LA CABECERA (SELECCIONAR TODOS) ---
    def _on_header_clicked(self, logicalIndex):
        if logicalIndex == 0:
            # Solo las filas de la fase actual: en la fase 2, las unidades del cliente abierto
            vins_visibles = {v for r in range(self.model.rowCount())
                             for v in self._vins_de_clave(self.model.clave_de_fila(r))}
            self._all_checked = not (vins_visibles and vins_visibles <= self.checked_vins)
            if self._all_checked:
                self.checked_vins.update(vins_visibles)
            else:
                self.checked_vins.difference_update(vins_visibles)

            # Un solo dataChanged para toda la columna de checks (Qt solo
            # repinta lo visible), en vez del loop anterior sobre cada
            # QTableWidgetItem. _on_model_data_changed ya llama a
            # _update_summary() cuando cambia la columna 0, no hace falta
            # llamarla de nuevo aqui.
            n = self.model.rowCount()
            if n > 0:
                self.model.dataChanged.emit(
                    self.model.index(0, 0), self.model.index(n - 1, 0), [Qt.ItemDataRole.CheckStateRole]
                )
            else:
                self._update_summary()

    # --- MENÚ CONTEXTUAL (AGREGAR CORREO) ---
    def _show_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        cdb_fila, razon_social_fila, sin_correo_fila = self._resolver_cdb_razonsocial_por_fila(row)

        # Si el clic cae dentro de una selección múltiple se copian los VIN de todas esas filas
        seleccion = self.table.selectionModel()
        filas_sel = sorted({i.row() for i in seleccion.selectedRows()}) if seleccion else []
        filas_copiar = filas_sel if row in filas_sel and len(filas_sel) > 1 else [row]
        vins_copiar = []
        for r in filas_copiar:
            for vin in self._vins_de_clave(self.model.clave_de_fila(r)):
                if vin not in vins_copiar:
                    vins_copiar.append(vin)

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid #E5E7EB; border-radius: 6px; padding: 4px; } QMenu::item { padding: 6px 25px; border-radius: 4px; color: #1E293B; font-weight: bold; } QMenu::item:selected { background-color: #F3F4F6; color: #1C6BBA; }")
        action_copiar = None
        if vins_copiar:
            texto_copiar = f"Copiar VINs ({len(vins_copiar)})" if len(vins_copiar) > 1 else "Copiar VIN"
            action_copiar = QAction(qta.icon('fa5s.copy', color=TEXT_SECONDARY), texto_copiar, self)
            menu.addAction(action_copiar)
        action_agregar_correo = None
        if sin_correo_fila:
            action_agregar_correo = QAction(qta.icon('fa5s.user-plus', color=SUCCESS), "Agregar correo relacionado a esta empresa", self)
            menu.addAction(action_agregar_correo)
        if menu.isEmpty():
            return
        elegida = menu.exec(self.table.viewport().mapToGlobal(pos))
        if elegida is None:
            return
        if elegida == action_copiar:
            QApplication.clipboard().setText("\n".join(vins_copiar))
        elif elegida == action_agregar_correo:
            self._abrir_agregar_correo(cdb_fila, razon_social_fila)

    def _resolver_cdb_razonsocial_por_fila(self, row):
        """Devuelve (cdb, razon_social, sin_correo) para la fila `row` de la
        tabla visible, resolviendo el CDB vía self._vin_cdb_map (Correos.csv
        no trae columna CDB propia). Una fila de cliente usa la primera unidad
        de ese cliente; una fila de unidad usa su propio VIN."""
        vins = self._vins_de_clave(self.model.clave_de_fila(row))
        if not vins or self.df_display.empty:
            return "", "", False
        unidades = self.df_display[self.df_display['VIN'].astype(str) == vins[0]]
        if unidades.empty:
            return "", "", False
        r_data = unidades.iloc[0]
        if self._grupo_abierto is None:
            correos = self._correos_de(self.df_display[self.df_display['VIN'].astype(str).isin(vins)]['CORREO ELECTRÓNICO'])
            sin_correo = not correos
        else:
            sin_correo = str(r_data.get('CORREO ELECTRÓNICO', '')).strip() == ""
        return self._vin_cdb_map.get(vins[0], ""), str(r_data.get('RAZÓN SOCIAL', '')), sin_correo

    def _abrir_agregar_correo(self, cdb, razon_social):
        if not cdb:
            QMessageBox.warning(self, "CDB flota no encontrado", "No se pudo determinar el CDB flota de esta empresa a partir de la base Comercial.")
            return

        dialog = ContactosAddDialog(self, cdb_prefill=cdb, flota_prefill=razon_social)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dialog.get_data()

        try:
            df_contactos_actual = pd.read_excel(CONTACTOS_EXCEL_PATH) if CONTACTOS_EXCEL_PATH and os.path.exists(CONTACTOS_EXCEL_PATH) else pd.DataFrame()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo leer contactos.xlsx:\n{e}")
            return

        if not df_contactos_actual.empty and 'ID' in df_contactos_actual.columns:
            try:
                max_id = pd.to_numeric(df_contactos_actual['ID'], errors='coerce').max()
                new_id = int(max_id) + 1 if pd.notna(max_id) else 1
            except Exception:
                new_id = 1
        else:
            new_id = 1
        new_data['ID'] = str(new_id)

        ok_add = ExcelWriter().add_new_row(new_data, module_name="Contactos", custom_filepath=CONTACTOS_EXCEL_PATH)
        if not ok_add:
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto en SharePoint. Verifica si contactos.xlsx está abierto.")
            return

        QMessageBox.information(self, "Contacto agregado", f"Se agregó el contacto para la flota: {razon_social}")

        # Mismo mecanismo que usa la pantalla Contactos para refrescar el caché global
        self.data_manager.load_contactos_async()

        try:
            df_contactos_actualizado = pd.read_excel(CONTACTOS_EXCEL_PATH)
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"El contacto se guardó, pero no se pudo releer contactos.xlsx para actualizar Correos.csv:\n{e}")
            self._load_correos_file()
            return

        df_comercial = self.data_manager.get_comercial_df()
        ok_correo, msg_correo, _ = contacto_correo_service.actualizar_correo_por_cdb(cdb, df_comercial, df_contactos_actualizado, CORREOS_EXCEL_PATH)
        if not ok_correo:
            QMessageBox.warning(self, "Aviso", f"El contacto se guardó en Contactos, pero no se pudo actualizar Correos.csv:\n{msg_correo}")

        self._load_correos_file()

    def _populate_table(self, text=""):
        if self.df_correos.empty:
            self.df_display = pd.DataFrame()
            self._grupo_abierto = None
            self._render_table()
            return

        # Instrumentacion temporal (auditoria de rendimiento B-5, 18-09-2026):
        # mide el costo de la busqueda/filtrado interno, separado de la
        # lectura del Excel y del render. No cambia el comportamiento.
        with medir(f"B-5 MailDialog > filtrado interno ({len(self.df_correos)} filas base)"):
            df_show = self.df_correos.copy()

            # Filtro de Plan
            plan_filter = self.combo_plan.currentText()
            if plan_filter != "Todos los Planes":
                df_show = df_show[df_show['TIPO DE SERVICIO'].astype(str).str.strip().str.upper() == plan_filter.upper()]

            # Filtro de Buscador (VIN o Razón Social). B-5.3 (auditoria de
            # rendimiento, 18-09-2026): antes era un loop propio O(terminos x
            # columnas) -- igual al que ya se reemplazo en general.py para
            # B-2 -- medido en ~540ms para 50 VINs pegados sobre 12.000 filas.
            # comercial_services.construir_mascara_busqueda ya resuelve la
            # MISMA semantica (','=OR entre terminos, espacio=AND dentro de
            # un termino, substring case-insensitive) con una sola regex de
            # alternancia por columna para los terminos simples, en vez de un
            # .str.contains() por termino y columna. Verificado termino a
            # termino contra el loop anterior antes de reemplazarlo: mismo
            # resultado para 1 termino, varios VIN con coma, terminos
            # compuestos con espacio, sin resultados y vacio (este ultimo
            # caso ni siquiera se alcanza, sigue guardado por el `if
            # text_search:` de arriba, igual que antes).
            text_search = self.search_bar.text().strip().lower()
            if text_search:
                cols = [c for c in ['VIN', 'RAZÓN SOCIAL', 'RUT'] if c in df_show.columns]
                mask = comercial_services.construir_mascara_busqueda(df_show, text_search, cols)
                df_show = df_show[mask]

            # Conteos de cada bandeja con el plan y la búsqueda ya aplicados
            mask_xvencer = mascara_por_vencer(df_show)
            mask_sin_correo = mascara_sin_correo(df_show)
            self._actualizar_conteos_bandeja(len(df_show), int(mask_xvencer.sum()), int(mask_sin_correo.sum()))

            if self.current_kpi == "xvencer":
                df_show = df_show[mask_xvencer]
            elif self.current_kpi == "sincorreo":
                df_show = df_show[mask_sin_correo]
            elif self.current_kpi == "concorreo":
                df_show = df_show[~mask_sin_correo]

            self.df_display = df_show.reset_index(drop=True)
        if self._grupo_abierto is not None and self._grupo_abierto not in set(self._serie_clave(self.df_display)):
            self._grupo_abierto = None
        with medir(f"B-5 MailDialog > _render_table ({len(self.df_display)} filas)"):
            self._render_table()

    def _actualizar_conteos_bandeja(self, total, por_vencer, sin_correo):
        base = max(1, len(self.df_correos))
        self._pintar_kpi('total', total, total / base, "Con los filtros actuales")
        self._pintar_kpi('xvencer', por_vencer, por_vencer / max(1, total),
                         estilo_com.formatear_porcentaje(por_vencer / max(1, total)).replace(" del total", "") + " · término en 30 días")
        self._pintar_kpi('sincorreo', sin_correo, sin_correo / max(1, total),
                         "Agrégalo con clic derecho")
        con_correo = total - sin_correo
        self._pintar_kpi('concorreo', con_correo, con_correo / max(1, total), "Listos para enviar")

    # --- TABLA EN DOS FASES (CLIENTE -> UNIDADES) ---
    _COLUMNAS_CLIENTES = ["✔", "RAZÓN SOCIAL", "RUT", "CORREOS ASOCIADOS", "UNIDADES"]
    _COLUMNAS_UNIDADES = ["✔", "VIN", "PLAN", "FECHA TÉRMINO"]
    _ANCHOS_CLIENTES = {"✔": 46, "RAZÓN SOCIAL": 380, "RUT": 120, "CORREOS ASOCIADOS": 170, "UNIDADES": 110}
    _ANCHOS_UNIDADES = {"✔": 46, "VIN": 280, "PLAN": 200, "FECHA TÉRMINO": 180}
    _SIN_RAZON_SOCIAL = "(Sin razón social)"

    def _serie_clave(self, df):
        if df.empty or 'RAZÓN SOCIAL' not in df.columns:
            return pd.Series([], dtype=str)
        serie = df['RAZÓN SOCIAL'].astype(str).str.strip()
        return serie.mask(serie == "", self._SIN_RAZON_SOCIAL)

    @staticmethod
    def _correos_de(serie):
        """Correos distintos (sin repetir mayúsculas/minúsculas) de una columna con listas separadas por ';'."""
        vistos = {}
        for texto in serie.astype(str):
            for correo in texto.split(';'):
                correo = correo.strip()
                if correo:
                    vistos.setdefault(correo.lower(), correo)
        return list(vistos.values())

    def _vins_de_clave(self, clave):
        if self._grupo_abierto is not None:
            return [clave] if clave else []
        return self._vins_por_clave.get(clave, [])

    def _construir_vista(self):
        """DataFrame de la fase actual; deja en self._vins_por_clave los VIN de cada cliente."""
        df = self.df_display
        self._vins_por_clave = {}
        if df.empty:
            columnas = self._COLUMNAS_CLIENTES if self._grupo_abierto is None else self._COLUMNAS_UNIDADES
            return pd.DataFrame(columns=columnas), columnas[1]
        claves = self._serie_clave(df)
        if self._grupo_abierto is not None:
            sub = df[claves == self._grupo_abierto]
            vista = pd.DataFrame({
                "✔": "", "VIN": sub['VIN'].astype(str).values,
                "PLAN": sub['TIPO DE SERVICIO'].astype(str).values if 'TIPO DE SERVICIO' in sub.columns else "",
                "FECHA TÉRMINO": sub['FECHA TERMINO'].astype(str).values if 'FECHA TERMINO' in sub.columns else "",
            })
            return vista, "VIN"
        filas = []
        for clave, sub in df.assign(_clave=claves).groupby('_clave', sort=True):
            rut = next((r for r in sub['RUT'].astype(str) if r.strip()), "") if 'RUT' in sub.columns else ""
            n_correos = len(self._correos_de(sub['CORREO ELECTRÓNICO'])) if 'CORREO ELECTRÓNICO' in sub.columns else 0
            texto = "Sin correo" if n_correos == 0 else f"{n_correos} correo{'s' if n_correos != 1 else ''}"
            filas.append(["", clave, rut, texto, len(sub)])
            self._vins_por_clave[clave] = sub['VIN'].astype(str).tolist()
        return pd.DataFrame(filas, columns=self._COLUMNAS_CLIENTES), "RAZÓN SOCIAL"

    def _resolver_color(self, columna, valor, es_fondo):
        if columna == "CORREOS ASOCIADOS" and valor == "Sin correo":
            return estilo_com.ROJO_SUAVE if es_fondo else estilo_com.ROJO
        if columna == "FECHA TÉRMINO" and not es_fondo and valor:
            fecha = pd.to_datetime(valor, format='%d-%m-%Y', errors='coerce')
            if pd.notna(fecha) and 0 <= (fecha - pd.Timestamp(datetime.now().date())).days <= 30:
                return estilo_com.AMBAR
        return None

    def _on_tabla_clic(self, index):
        if self._grupo_abierto is not None or not index.isValid() or index.column() == 0:
            return
        clave = self.model.clave_de_fila(index.row())
        if clave:
            self._grupo_abierto = clave
            self._render_table()

    def _cerrar_grupo(self):
        self._grupo_abierto = None
        self._render_table()

    def _render_table(self):
        vista, columna_clave = self._construir_vista()
        vista = self.table.apply_sort(vista)
        self.model.set_vista(vista, columna_clave)
        anchos = self._ANCHOS_CLIENTES if self._grupo_abierto is None else self._ANCHOS_UNIDADES
        for i, columna in enumerate(vista.columns):
            self.table.setColumnWidth(i, anchos.get(columna, 140))
        self.btn_volver.setVisible(self._grupo_abierto is not None)
        self._update_summary()

    def _on_model_data_changed(self, top_left, bottom_right, roles=None):
        # Reemplaza a _on_table_item_changed (esa señal era exclusiva de
        # QTableWidgetItem): ModeloCorreosAgrupado.setData() ya actualiza
        # self.checked_vins directamente (es el mismo set, pasado por
        # referencia) y emite dataChanged; aquí solo falta refrescar el
        # resumen cuando lo que cambió fue la columna de checks.
        if top_left.column() == 0:
            self._update_summary()

    def _filas_marcadas(self):
        """Filas visibles marcadas (mismo criterio que antes: checked_vins
        cruzado con df_display), como dicts listos para mail_service."""
        if self.df_display.empty or not self.checked_vins:
            return []
        sel = self.df_display[self.df_display['VIN'].astype(str).isin(self.checked_vins)]
        def col(nombre):
            return sel[nombre].astype(str) if nombre in sel.columns else pd.Series([""] * len(sel), index=sel.index)
        return [
            {'vin': v, 'flota': f, 'plan': p, 'correo': c.strip()}
            for v, f, p, c in zip(col('VIN'), col('RAZÓN SOCIAL'), col('TIPO DE SERVICIO'), col('CORREO ELECTRÓNICO'))
        ]

    def _update_summary(self):
        # Misma agrupación (razón social + correo) que usa el envío real
        filas = self._filas_marcadas()
        grupos = mail_service.agrupar_destinatarios(filas)
        sin_correo = [g for g in grupos if not g['correo']]

        while self._lista_destinatarios.count():
            w = self._lista_destinatarios.takeAt(0).widget()
            if w is not None:
                # Se oculta ya: deleteLater solo borra al volver al bucle de eventos
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if not grupos:
            vacio = QLabel("Marca unidades en la tabla para ver a quién le llegará el correo.")
            vacio.setWordWrap(True)
            vacio.setStyleSheet(estilo_com.QSS_FICHA_VACIA)
            self._lista_destinatarios.addWidget(vacio)
        for grupo in grupos[:self._MAX_DESTINATARIOS_VISIBLES]:
            self._lista_destinatarios.addWidget(self._crear_item_destinatario(grupo))
        resto = len(grupos) - self._MAX_DESTINATARIOS_VISIBLES
        if resto > 0:
            mas = QLabel(f"y {resto} destinatario{'s' if resto != 1 else ''} más")
            mas.setStyleSheet(estilo_com.QSS_FICHA_VACIA)
            self._lista_destinatarios.addWidget(mas)
        self.lbl_titulo_destinatarios.setText(f"DESTINATARIOS ({len(grupos)})")

        n = len(grupos)
        self.btn_send.setText(f" Abrir {n} borrador{'es' if n != 1 else ''} en Outlook" if n else " Abrir en Outlook")
        if sin_correo:
            nombres = ", ".join(g['flota'] for g in sin_correo[:3]) + ("…" if len(sin_correo) > 3 else "")
            self.lbl_aviso_sin_correo.setText(
                f"⚠ {len(sin_correo)} sin correo ({nombres}): su borrador se abrirá sin destinatario. "
                "Agrégalo con clic derecho en su fila o complétalo en Outlook."
            )
        self.lbl_aviso_sin_correo.setVisible(bool(sin_correo))
        self._mostrar_panel(self._grupo_abierto is not None and bool(filas))

        if self._grupo_abierto is None:
            detalle = f"{len(self._vins_por_clave):,} clientes".replace(",", ".")
        else:
            n_unidades = len(self.model.get_df())
            detalle = f"{n_unidades} unidades · {self._grupo_abierto}"
        self.lbl_conteo_tabla.setText(
            f"<span style='color:{estilo_com.PRIMARIO}; font-weight:700'>{len(filas)} marcadas</span> · {detalle}"
        )

    def _on_plantilla_changed(self, text):
        if "Personalizado" in text:
            self.txt_asunto.setReadOnly(False); self.txt_mensaje.setReadOnly(False)
            self.txt_asunto.setText(""); self.txt_mensaje.setHtml("")
            self.txt_mensaje.setPlaceholderText("Escribe tu mensaje aquí...\nPuedes usar @NOMBRE para saludar al contacto y @FLOTA para referirte a la empresa.")
        else:
            self.txt_asunto.setReadOnly(True); self.txt_mensaje.setReadOnly(True)
            config_plantilla = mail_service.obtener_configuracion_plantilla(text)
            self.txt_asunto.setText(config_plantilla['asunto'] if config_plantilla else "")
            self.txt_asunto.setCursorPosition(0)
            self.txt_mensaje.setHtml(f"<div><br><br><center><span style='font-size: 14px; color: #9CA3AF;'>Al presionar Enviar, Outlook se abrirá mostrando el diseño corporativo pre-armado para que lo revises antes de enviarlo al cliente.</span></center></div>")

    def enviar_correos(self):
        # B-5 (auditoria de rendimiento, 18-09-2026): antes recorria
        # self.table.rowCount() consultando cada QTableWidgetItem; mismo
        # criterio que _update_summary ahora -- self.checked_vins cruzado
        # contra df_display (las filas actualmente visibles/filtradas).
        filas_seleccionadas = self._filas_marcadas()

        if not filas_seleccionadas:
            return QMessageBox.warning(self, "Aviso", "Debes marcar al menos un checkbox en la tabla para enviar.")

        plantilla = self.combo_plantilla.currentText()
        if "Personalizado" in plantilla and (not self.txt_asunto.text().strip() or not self.txt_mensaje.toPlainText().strip()):
            return QMessageBox.warning(self, "Aviso", "Debes redactar un Asunto y un Mensaje.")

        # Se permite enviar aunque falte correo: Outlook se abre igual y el
        # usuario completa el destinatario manualmente.
        final_dest_list = mail_service.agrupar_destinatarios(filas_seleccionadas)

        self.btn_send.setEnabled(False)
        mostrar_guardando(self, "Generando correos en Outlook…")

        cc = self.txt_cc.text().strip()
        clean_plantilla = "Personalizado" if "Personalizado" in plantilla else plantilla

        self.sender_thread = OutlookSenderThread(final_dest_list, cc, clean_plantilla, self.txt_asunto.text(), self.txt_mensaje.toPlainText())
        self.sender_thread.finished_signal.connect(self._on_finished)
        self.sender_thread.registrado_signal.connect(DataManager().correos_registrados.emit)
        self.sender_thread.start()

    def _on_finished(self, exitos, fallos, registro_ok):
        self.btn_send.setEnabled(True)
        aviso_registro = "\n\n⚠️ Aviso: los correos se generaron, pero no se pudo guardar el registro en el historial de envíos." if not registro_ok else ""
        terminar_guardando(self, exito=(fallos == 0), texto_exito="Correos generados")
        if fallos == 0:
            if aviso_registro:
                QMessageBox.warning(self, "Aviso", f"Se generaron {exitos} ventanas de correo.{aviso_registro}")
        else:
            QMessageBox.warning(self, "Problemas en Outlook", f"Se generaron {exitos} correos, pero Outlook rechazó {fallos} intentos.\n\nAsegúrate de no tener Outlook bloqueado.{aviso_registro}")