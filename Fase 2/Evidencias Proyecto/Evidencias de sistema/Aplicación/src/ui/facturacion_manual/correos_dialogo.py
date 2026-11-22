"""Correos de facturación: revisión de los correos a los administradores de flota y apertura de cada uno en Outlook."""
import logging
import os
import time
from datetime import datetime

import pandas as pd
import qtawesome as qta
from PyQt6.QtCore import QEvent, QPointF, QRectF, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton, QVBoxLayout

import config.settings
from src.services import mail_registro, mail_service
from src.theme import tema
from src.ui.administracion import estilo as admin_estilo
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.compartido.mail_dialog import _DelegadoCasilla
from src.ui.ingresos.base import ModeloTablaIngresos, aplicar_estilo_tabla_lectura

logger = logging.getLogger(__name__)

_COLUMNAS = ["✔", "FLOTA", "CORREO", "PLANTILLA", "ARCHIVOS", "UNIDADES"]
_ANCHOS = {"✔": 46, "FLOTA": 300, "CORREO": 250, "PLANTILLA": 130, "ARCHIVOS": 120, "UNIDADES": 100}
_ETIQUETA_TIPO = {"OC": "OC", "FACTURA": "Factura"}
_SIN_CORREO = "Sin correo"


class _ModeloFlotas(ModeloTablaIngresos):
    """Tabla de flotas con casilla en la primera columna; las marcadas viven en el set `marcadas` del diálogo."""

    def __init__(self, marcadas, puede_marcar, **kwargs):
        super().__init__(**kwargs)
        self._marcadas = marcadas
        self._puede_marcar = puede_marcar

    def clave_de_fila(self, fila):
        return str(self._df.iat[fila, 1]) if 0 <= fila < len(self._df) else ""

    def flags(self, index):
        base = super().flags(index)
        if index.isValid() and index.column() == 0:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if self.clave_de_fila(index.row()) in self._marcadas else Qt.CheckState.Unchecked
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return None
        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        clave = self.clave_de_fila(index.row())
        if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, 2) and self._puede_marcar(clave):
            self._marcadas.add(clave)
        else:
            self._marcadas.discard(clave)
        self.dataChanged.emit(index, index, [role])
        return True


class EnvioFacturacionThread(QThread):
    """Abre en Outlook un correo por flota, con sus archivos adjuntos, y espera a que se envíe o se cierre antes de mostrar el
    siguiente (que ya deja armado mientras tanto, para que aparezca al instante). Cada correo se anota en el Registro de envíos.
    `cancelar()` lo detiene: no se abre ningún correo más."""
    progreso = pyqtSignal(int, str)
    terminado = pyqtSignal(int, int, int, int, bool)  # enviados, cerrados sin enviar, fallidos, sin abrir, historial ok

    def __init__(self, correos):
        super().__init__()
        self.correos = correos
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    @staticmethod
    def _crear(outlook, c, assets, sink):
        """Arma el correo con sus imágenes y archivos, sin mostrarlo; devuelve (correo, estado de cierre, con eventos)."""
        import win32com.client
        estado = {'cerrado': False, 'enviado': False}
        try:
            mail = win32com.client.DispatchWithEvents(outlook.CreateItem(0), sink(estado))
            con_eventos = True
        except Exception:
            mail = outlook.CreateItem(0)
            con_eventos = False
        mail.To = c['correo']
        if c['cc']:
            mail.CC = c['cc']
        try:
            mail.Recipients.ResolveAll()
        except Exception:
            pass
        mail.Subject = c['asunto']
        mail.HTMLBody = c['html']
        for archivo, cid in mail_service.IMAGENES_FACTURACION:
            ruta = os.path.join(assets, archivo)
            if os.path.exists(ruta):
                adj = mail.Attachments.Add(ruta)
                adj.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", cid)
        for ruta in c['archivos']:
            if os.path.exists(ruta):
                mail.Attachments.Add(ruta)
        return mail, estado, con_eventos

    @staticmethod
    def _descartar(armado):
        try:
            armado[0].Close(1)  # olDiscard
        except Exception:
            pass

    def run(self):
        import pythoncom
        import win32com.client
        from src.ui.compartido import mail_dialog

        pythoncom.CoInitialize()
        enviados = cerrados = fallidos = sin_abrir = 0
        registro_ok = True
        id_envio = datetime.now().strftime("ENV-%Y%m%d-%H%M%S")
        assets = mail_dialog.get_resource_path(os.path.join('src', 'assets'))
        sink = mail_dialog._crear_sink_cierre
        siguiente = None
        n = len(self.correos)
        try:
            outlook = win32com.client.Dispatch('outlook.application')
            for i, c in enumerate(self.correos):
                if self._cancelado:
                    sin_abrir = n - i
                    break
                self.progreso.emit(i, f"Preparando el correo de {c['flota']}…")
                armado, siguiente = siguiente, None
                if armado is not None:
                    try:
                        armado[0].Display()
                    except Exception:
                        armado = None
                reconexiones = 0
                for intento in range(90):
                    if armado is not None or self._cancelado:
                        break
                    nuevo = None
                    try:
                        nuevo = self._crear(outlook, c, assets, sink)
                        nuevo[0].Display()
                        armado = nuevo
                    except Exception as e:
                        if nuevo is not None:
                            self._descartar(nuevo)
                        armado = None
                        texto = str(e).lower()
                        if "dialog box is open" in texto or "cuadro de di" in texto:
                            # Outlook sigue con una ventana abierta (por ejemplo, preguntando si guarda el borrador que se cerró)
                            self.progreso.emit(i, "Outlook tiene un cuadro de diálogo abierto: respóndelo o ciérralo para continuar…")
                            self._esperar(1.5)
                        elif reconexiones < 3 and ("-2147023174" in texto or "-2147023170" in texto or "rpc" in texto):
                            reconexiones += 1
                            self._esperar(1.5)
                            try:
                                outlook = win32com.client.Dispatch('outlook.application')
                            except Exception:
                                pass
                        else:
                            logger.warning(f"No se pudo preparar el correo de facturación de {c['flota']}: {e}")
                            break
                if self._cancelado and armado is None:
                    sin_abrir = n - i
                    break
                if armado is None:
                    fallidos += 1
                    continue
                mail, estado, con_eventos = armado
                try:
                    resultado = "ENVIADO A OUTLOOK"
                    if con_eventos:
                        self.progreso.emit(i, f"Esperando que envíes o cierres el correo de {c['flota']}…")
                        # Mientras este correo está abierto se arma el siguiente, para que aparezca al instante
                        if i + 1 < n and not self._cancelado:
                            try:
                                siguiente = self._crear(outlook, self.correos[i + 1], assets, sink)
                            except Exception as e:
                                logger.info(f"No se pudo adelantar el siguiente correo: {e}")
                                siguiente = None
                        sondeo = 0
                        while not estado['cerrado'] and not self._cancelado:
                            pythoncom.PumpWaitingMessages()
                            time.sleep(0.1)
                            sondeo += 1
                            if sondeo % 10 == 0:
                                try:
                                    outlook.Version
                                except Exception:
                                    raise RuntimeError("Outlook se cerró")
                        if self._cancelado and not estado['cerrado']:
                            # Se detuvo con este correo abierto: queda en Outlook para que lo envíes o lo cierres
                            sin_abrir = n - i - 1
                            break
                        resultado = "ENVIADO" if estado['enviado'] else "CERRADO SIN ENVIAR"
                    if resultado == "CERRADO SIN ENVIAR":
                        cerrados += 1
                    else:
                        enviados += 1
                    registro_ok &= mail_registro.registrar_envios([mail_registro.construir_registro(
                        id_envio=id_envio, fecha_hora=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        tipo_correo=c['tipo_registro'], razon_social=c['flota'], chasis="", destinatario=c['correo'],
                        estado=resultado, asunto=c['asunto'])])
                except Exception as e:
                    logger.warning(f"Se perdió la conexión con Outlook en el correo de {c['flota']}: {e}")
                    fallidos += n - i
                    siguiente = None
                    break
                self._esperar(0.3)
        except Exception as e:
            fallidos += max(0, n - enviados - cerrados - fallidos - sin_abrir)
            logger.error(f"Error conectando con Outlook: {e}", exc_info=True)
        finally:
            if siguiente is not None:
                self._descartar(siguiente)
            pythoncom.CoUninitialize()
        self.terminado.emit(enviados, cerrados, fallidos, sin_abrir, registro_ok)

    @staticmethod
    def _esperar(segundos):
        """Pausa atendiendo los mensajes de COM (Outlook no responde si el hilo solo duerme)."""
        import pythoncom
        fin = time.time() + segundos
        while time.time() < fin:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.1)


class DialogoCorreosFacturacion(QDialog):
    """`salidas`: por flota {'flota', 'archivos', 'tipos', 'vins'}. Misma presentación del Gestor de Correos: barra con la
    búsqueda, tarjetas con los conteos y una tabla con una fila por flota (correo de Correos.csv según sus VIN, plantilla
    según OC o factura manual y archivos). Doble clic o clic derecho en una fila cambia su correo."""

    def __init__(self, padre, salidas, etiqueta_periodo):
        super().__init__(padre)
        self.setWindowTitle("Correos de facturación")
        self.setModal(True)
        self.resize(1040, 680)
        self.setStyleSheet(f"QDialog {{ background: {estilo_com.SUPERFICIE}; }}")
        self._mes = etiqueta_periodo.lower()
        self._hilo = None
        self._cerrar_al_terminar = False
        self._filas = self._armar_filas(salidas)
        self.marcadas = {f['clave'] for f in self._filas if f['correo']}

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 16)
        raiz.setSpacing(12)

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar flota o correo")
        self.buscador.setClearButtonEnabled(True)
        estilo_barra = ("QLineEdit { background-color: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.18);"
                        " border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; }"
                        "QLineEdit:focus { border: 1px solid rgba(255,255,255,0.55); }")
        self.buscador.setStyleSheet(estilo_barra)
        self.buscador.addAction(qta.icon('fa5s.search', color='#B8C2D6'), QLineEdit.ActionPosition.LeadingPosition)
        self.buscador.textChanged.connect(self._pintar_tabla)
        self.cc = QLineEdit()
        self.cc.setPlaceholderText("CC opcional (varios con ;)")
        self.cc.setStyleSheet(estilo_barra)
        self.cc.setMinimumWidth(240)
        barra = admin_estilo.barra_opciones('fa5s.envelope', "", "", mostrar_titulo=False, con_grupos=False)
        barra.zona_filtros.addWidget(self.buscador, 1)
        barra.zona_filtros.addWidget(self.cc)
        raiz.addWidget(barra.marco)

        contenedor, tarjetas = admin_estilo.fila_kpis(4)
        self._kpis = {}
        for tarjeta, (clave, titulo, color, ayuda) in zip(tarjetas, (
                ('total', "Flotas", estilo_com.PRIMARIO, f"Flotas con archivos generados en {self._mes}."),
                ('con', "Con correo", estilo_com.VERDE, "Flotas con un correo del administrador en Correos.csv."),
                ('sin', "Sin correo", estilo_com.ROJO, "Flotas sin correo: escríbelo con doble clic en la fila."),
                ('marcadas', "Para enviar", estilo_com.AMBAR, "Correos que se abrirán en Outlook."))):
            tarjeta.definir(titulo, color, ayuda)
            self._kpis[clave] = tarjeta
        raiz.addWidget(contenedor)

        fila_estado = QHBoxLayout()
        fila_estado.setContentsMargins(4, 0, 4, 0)
        titulo = QLabel(f"Flotas · {self._mes}")
        titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 13px; font-weight: bold; background: transparent; border: none;")
        ayuda = QLabel("Casilla para marcar · doble clic o clic derecho para cambiar el correo")
        ayuda.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
        fila_estado.addWidget(titulo)
        fila_estado.addStretch(1)
        fila_estado.addWidget(ayuda)
        raiz.addLayout(fila_estado)

        self.model = _ModeloFlotas(self.marcadas, self._puede_marcar, resolver=self._resolver_color,
                                   alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model.dataChanged.connect(lambda *_a: self._actualizar())
        self.tabla = VolvoTableWidget()
        aplicar_estilo_tabla_lectura(self.tabla, 44)
        self.tabla.set_model_and_delegate(self.model)
        self._delegado = _DelegadoCasilla([self.tabla, self.tabla.frozen_view])
        self.tabla.setItemDelegate(self._delegado)
        self.tabla.frozen_view.setItemDelegate(self._delegado)
        self.tabla.sort_changed.connect(self._pintar_tabla)
        self.tabla.doubleClicked.connect(self._doble_clic)
        self.tabla.customContextMenuRequested.disconnect()
        self.tabla.customContextMenuRequested.connect(self._menu_contexto)
        tarjeta_tabla, lay_tabla = admin_estilo.tarjeta_contenido("tarjetaTablaCorreosFacturacion")
        lay_tabla.addWidget(self.tabla, 1)
        raiz.addWidget(tarjeta_tabla, 1)

        pie = QHBoxLayout()
        self.lbl_estado = QLabel()
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; background: transparent; border: none;")
        pie.addWidget(self.lbl_estado, 1)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_cancelar.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; border-radius: 8px; padding: 9px 22px;"
            " font-size: 13px; font-weight: 600; } QPushButton:hover { background: #F4F7FB; }")
        self.btn_cancelar.clicked.connect(self.reject)
        self.btn_abrir = QPushButton("Abrir en Outlook")
        self.btn_abrir.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_abrir.setStyleSheet(
            "QPushButton { background: #1B2B4E; color: white; border: 1px solid #1B2B4E; border-radius: 8px; padding: 9px 22px;"
            " font-size: 13px; font-weight: 700; } QPushButton:hover { background: #2C4A80; border-color: #2C4A80; }"
            " QPushButton:disabled { background: #A9B4C6; border-color: #A9B4C6; }")
        self.btn_abrir.clicked.connect(self._abrir_en_outlook)
        pie.addWidget(self.btn_cancelar)
        pie.addWidget(self.btn_abrir)
        raiz.addLayout(pie)
        self._pintar_tabla()

    # ------------------------------------------------------------ datos
    def _armar_filas(self, salidas):
        correos = self._leer_correos()
        filas, usados = [], set()
        for s in salidas:
            clave = s['flota']
            while clave in usados:
                clave += " (2)"
            usados.add(clave)
            opciones = mail_service.correos_de_flota(correos, s['vins'])
            tipos = mail_service._tipos_facturacion(s['tipos'])
            filas.append({'clave': clave, 'flota': s['flota'], 'opciones': opciones, 'correo': opciones[0] if opciones else "",
                          'tipos': s['tipos'], 'archivos': list(s['archivos']), 'unidades': len(s['vins']),
                          'plantilla': " y ".join(_ETIQUETA_TIPO[x] for x in ("OC", "FACTURA") if x in tipos)})
        return filas

    @staticmethod
    def _leer_correos():
        ruta = getattr(config.settings, 'CORREOS_EXCEL_PATH', '')
        if ruta and os.path.exists(ruta):
            try:
                return pd.read_csv(ruta, dtype=str, keep_default_na=False)
            except Exception as e:
                logger.warning(f"No se pudo leer Correos.csv: {e}")
        return pd.DataFrame()

    @staticmethod
    def _texto_archivos(archivos):
        pdf = sum(1 for a in archivos if a.lower().endswith('.pdf'))
        xls = sum(1 for a in archivos if a.lower().endswith('.xlsx'))
        return "PDF + Excel" if pdf == 1 and xls == 1 else f"{pdf} PDF + {xls} Excel"

    def _fila(self, clave):
        return next((f for f in self._filas if f['clave'] == clave), None)

    def _puede_marcar(self, clave):
        fila = self._fila(clave)
        return bool(fila and "@" in fila['correo'])

    # ------------------------------------------------------------ tabla
    def _pintar_tabla(self, *_):
        texto = self.buscador.text().strip().lower()
        filas = [f for f in self._filas if not texto or texto in f['flota'].lower() or texto in f['correo'].lower()]
        vista = pd.DataFrame([["", f['clave'], f['correo'] or _SIN_CORREO, f['plantilla'], self._texto_archivos(f['archivos']), f['unidades']]
                              for f in filas], columns=_COLUMNAS)
        vista = self.tabla.apply_sort(vista)
        self.model.set_data(vista)
        for i, columna in enumerate(vista.columns):
            self.tabla.setColumnWidth(i, _ANCHOS.get(columna, 140))
        self._actualizar()

    def _resolver_color(self, columna, valor, es_fondo):
        if columna == "CORREO" and valor == _SIN_CORREO:
            return estilo_com.ROJO_SUAVE if es_fondo else estilo_com.ROJO
        return None

    def _actualizar(self):
        total = len(self._filas)
        con = sum(1 for f in self._filas if "@" in f['correo'])
        n = len(self.marcadas)
        for clave, valor, fraccion, pie in (
                ('total', total, 1.0, f"{self._mes}"),
                ('con', con, con / max(1, total), "Listas para enviar"),
                ('sin', total - con, (total - con) / max(1, total), "Doble clic para escribirlo"),
                ('marcadas', n, n / max(1, total), "Marcadas en la tabla")):
            self._kpis[clave].actualizar(f"{valor:,}".replace(",", "."), fraccion, pie)
        self.btn_abrir.setText(f"Abrir en Outlook ({n})")
        self.btn_abrir.setEnabled(n > 0 and self._hilo is None)
        if self._hilo is None:
            self.lbl_estado.setText("Los correos se abren como borrador en Outlook: tú los revisas y los envías.")

    # ------------------------------------------------------------ cambiar el correo
    def _doble_clic(self, index):
        if index.isValid() and index.column() != 0:
            self.cambiar_correo(self.model.clave_de_fila(index.row()))

    def _menu_contexto(self, pos):
        index = self.tabla.indexAt(pos)
        if not index.isValid():
            return
        clave = self.model.clave_de_fila(index.row())
        from src.ui.compartido.menu_contextual import crear_menu
        menu = crear_menu(self)
        menu.accion("Cambiar correo…", 'fa5s.edit').triggered.connect(lambda: self.cambiar_correo(clave))
        menu.exec(self.tabla.viewport().mapToGlobal(pos))

    def cambiar_correo(self, clave):
        fila = self._fila(clave)
        if fila is None or self._hilo is not None:
            return
        opciones = list(fila['opciones'])
        if fila['correo'] and fila['correo'] not in opciones:
            opciones.insert(0, fila['correo'])
        indice = opciones.index(fila['correo']) if fila['correo'] in opciones else 0
        texto, ok = QInputDialog.getItem(self, "Correo de la flota", f"Correo del administrador de {fila['flota']}\n"
                                         "(elige uno de Correos.csv o escribe otro; varios con ;)", opciones or [""], indice, True)
        if ok:
            self.fijar_correo(clave, texto)

    def fijar_correo(self, clave, correo):
        fila = self._fila(clave)
        if fila is None:
            return
        fila['correo'] = correo.strip()
        if "@" in fila['correo']:
            self.marcadas.add(clave)
        else:
            self.marcadas.discard(clave)
        self._pintar_tabla()

    # ------------------------------------------------------------ envío
    def armar_correos(self):
        cc = self.cc.text().strip()
        correos = []
        for f in self._filas:
            if f['clave'] not in self.marcadas or "@" not in f['correo']:
                continue
            asunto, html = mail_service.correo_facturacion(f['tipos'], self._mes, f['flota'])
            correos.append({'flota': f['flota'], 'correo': f['correo'], 'cc': cc, 'asunto': asunto, 'html': html,
                            'archivos': list(f['archivos']), 'tipo_registro': mail_service.tipo_registro_facturacion(f['tipos'])})
        return correos

    def _abrir_en_outlook(self):
        correos = self.armar_correos()
        if not correos:
            return
        self.btn_abrir.setEnabled(False)
        self.btn_cancelar.setText("Detener")
        self.tabla.setEnabled(False)
        self.cc.setEnabled(False)
        self.buscador.setEnabled(False)
        self._total = len(correos)
        self._hilo = EnvioFacturacionThread(correos)
        self._hilo.progreso.connect(lambda i, texto: self.lbl_estado.setText(f"Correo {i + 1} de {self._total}: {texto}"))
        self._hilo.terminado.connect(self._al_terminar)
        self._hilo.start()

    def _detener(self):
        """Corta el envío: no se abre ningún correo más. El que esté abierto en Outlook queda para que lo envíes o lo cierres."""
        if self._hilo is None:
            return
        self._hilo.cancelar()
        self.btn_cancelar.setEnabled(False)
        self.btn_cancelar.setText("Deteniendo…")
        self.lbl_estado.setText("Deteniendo: no se abrirán más correos…")

    def _al_terminar(self, enviados, cerrados, fallidos, sin_abrir, registro_ok):
        hilo, self._hilo = self._hilo, None
        if hilo is not None:
            hilo.wait(3000)
        if self._cerrar_al_terminar:
            QDialog.reject(self)
            return
        partes = [f"{enviados} enviados"]
        if cerrados:
            partes.append(f"{cerrados} cerrados sin enviar")
        if fallidos:
            partes.append(f"{fallidos} con error")
        if sin_abrir:
            partes.append(f"{sin_abrir} sin abrir (detenido)")
        sin = len(self._filas) - self._total
        if sin:
            partes.append(f"{sin} flotas sin correo o sin marcar")
        self.lbl_estado.setText("Listo: " + " · ".join(partes) + ("" if registro_ok else ". No se pudo anotar en el Registro de envíos."))
        self.btn_abrir.hide()
        self.btn_cancelar.setText("Cerrar")
        self.btn_cancelar.setEnabled(True)

    def reject(self):
        if self._hilo is not None:
            self._cerrar_al_terminar = True
            self._detener()
            return
        super().reject()
