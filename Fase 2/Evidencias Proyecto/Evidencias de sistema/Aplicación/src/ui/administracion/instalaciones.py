from datetime import datetime
import pandas as pd
import qtawesome as qta
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
                             QStackedWidget, QProgressBar, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QGridLayout,
                             QTextEdit, QLineEdit, QApplication)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTransform
from src.core.data_manager import DataManager
from src.ui.compartido.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.ingresos.base import ModeloTablaIngresos
from src.ui.administracion import estilo as admin_estilo
from src.ui.administracion import listas as admin_listas
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.administracion.catalogos import _ESTILO_COMBO
from src.ui.comercial_agregar import _QSS_CHECK_SERVICIO
from src.theme.theme_manager import ThemeManager 
from src.theme.colors import *
from config.settings import PROVISION_EXCEL_PATH, INSTALACIONES_PATH, POWERBI_EXCEL_PATH, CONTACTOS_EXCEL_PATH
from src.core.excel_writer import ExcelWriter
from src.services import powerbi_cache_service, provisiones_services, comercial_services
from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

logger = logging.getLogger(__name__)

# =========================================================
# WORKER: El encargado de cruzar Provisiones + Comercial + PowerBI + Contactos
# =========================================================
def _formatear_meses(valor):
    """Meses sin decimales ("60.0" -> "60"). Vacío si no hay dato o es 0
    (registro de Provisiones aún sin cantidad de meses); '-' y MENSUAL se
    conservan."""
    texto = str(valor).strip()
    if texto.lower() in ('', 'nan', 'none', '<na>'):
        return ""
    if texto.upper() in ('-', 'MENSUAL'):
        return texto.upper()
    try:
        numero = float(texto.replace(',', '.'))
    except ValueError:
        return texto
    return str(int(round(numero))) if numero > 0 else ""


def _elegir_contacto(contactos):
    """(nombre, correo, teléfono) de UN solo administrador de flota del CDB: el
    más reciente (Fecha de extracción) entre los que traen nombre, correo y
    teléfono; si ninguno está completo, el que tenga más datos y, a igualdad,
    el más reciente."""
    if contactos is None or contactos.empty:
        return "", "", ""

    def limpio(valor, telefono=False):
        texto = str(valor).strip()
        if telefono:
            texto = texto.split('.')[0]
        return "" if texto.lower() in ('nan', 'none', '<na>', '-', '0', '') else texto

    candidatos = []
    for _, fila in contactos.iterrows():
        nombre = " ".join(p for p in (limpio(fila.get('Nombre', '')), limpio(fila.get('Apellidos', ''))) if p)
        correo = limpio(fila.get('Correo electrónico', ''))
        telefono = limpio(fila.get('Número móvil', ''), telefono=True)
        fecha = pd.to_datetime(fila.get('Fecha de extracción'), errors='coerce')
        completos = sum(bool(v) for v in (nombre, correo, telefono))
        candidatos.append((completos, fecha if pd.notna(fecha) else pd.Timestamp.min, nombre, correo, telefono))
    _c, _f, nombre, correo, telefono = max(candidatos, key=lambda c: (c[0], c[1]))
    return nombre, correo, telefono


def _meses_sin_decimales(df):
    """Columna MESES de una hoja leída de Excel: 60.0 -> '60', vacío si no hay dato."""
    if df is not None and 'MESES' in df.columns:
        df = df.copy()
        df['MESES'] = df['MESES'].map(_formatear_meses)
    return df


def _mostrar_velo(widget, mensaje):
    # El guardado corre en el hilo principal: se pinta el velo antes de bloquear
    velo = mostrar_guardando(widget, mensaje)
    velo.repaint()
    QApplication.processEvents()


class InstalacionesSyncWorker(QThread):
    log_signal = pyqtSignal(str)          
    preview_signal = pyqtSignal(object, dict) 
    error_signal = pyqtSignal(str)        

    def __init__(self, df_comercial, vines_objetivo=None, vines_extra=None, usar_provision=True):
        super().__init__()
        self.df_comercial = df_comercial
        self.vines_objetivo = {str(v).strip().upper() for v in vines_objetivo} if vines_objetivo else None
        # VIN del RM que se suman a los de la provisión del último mes (o van
        # solos si `usar_provision` es False)
        self.vines_extra = {str(v).strip().upper() for v in vines_extra} if vines_extra else set()
        self.usar_provision = usar_provision
        self.vines_sin_provision = set()
        self.df_cruzado = None

    @staticmethod
    def _leer_bbdd():
        df = powerbi_cache_service.leer_bbdd_clientes_cm(POWERBI_EXCEL_PATH)
        if 'CDB' in df.columns:
            df['CDB_CLEAN'] = df['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            df = df.drop_duplicates(subset=['CDB_CLEAN'])
        return df

    @staticmethod
    def _leer_contactos():
        df = pd.read_excel(CONTACTOS_EXCEL_PATH)
        if 'CDB' in df.columns:
            df['CDB_CLEAN'] = df['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        return df

    def run(self):
        # El cruce es Python puro: con el intervalo por defecto deja sin turno al hilo de la interfaz y la animación se traba
        intervalo = sys.getswitchinterval()
        sys.setswitchinterval(0.0005)
        try:
            self._ejecutar()
        finally:
            sys.setswitchinterval(intervalo)

    def _ejecutar(self):
        try:
            self.log_signal.emit("[SISTEMA] Iniciando creación de Instalaciones...")
            
            t_inicio = perf_counter()
            # Los tres Excel se leen a la vez: leerlos uno tras otro era lo más lento del cruce
            lector = ThreadPoolExecutor(max_workers=3)
            lectura_prov = lector.submit(
                pd.read_excel, PROVISION_EXCEL_PATH, sheet_name="Prov",
                usecols=['VIN', 'Cantidad de Meses', 'AÑO - MES', 'CLIENTE', 'OBSERVACIONES'])
            lectura_bbdd = lector.submit(self._leer_bbdd) if POWERBI_EXCEL_PATH and os.path.exists(POWERBI_EXCEL_PATH) else None
            lectura_contactos = lector.submit(self._leer_contactos) if CONTACTOS_EXCEL_PATH and os.path.exists(CONTACTOS_EXCEL_PATH) else None

            self.log_signal.emit("[LEYENDO] Extrayendo VINs nuevos de Provisiones...")
            df_prov = lectura_prov.result()
            df_prov.dropna(subset=['VIN'], inplace=True)
            df_prov['VIN'] = df_prov['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper()
            
            meses_map = {
                'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
                'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
            }
            df_prov['AÑO - MES'] = df_prov['AÑO - MES'].astype(str).str.strip()
            df_prov_todo = df_prov.copy()
            fechas_unicas = [f for f in df_prov['AÑO - MES'].unique() if "-" in f]

            def _orden_periodo(f):
                partes = str(f).split("-")
                try:
                    return (int(partes[0].strip()), meses_map.get(partes[1].strip().capitalize(), 0))
                except (ValueError, IndexError):
                    return (0, 0)

            if self.vines_objetivo:
                # VIN concretos: se usa su provisión más reciente, sin filtrar por mes
                df_prov = df_prov[df_prov['VIN'].isin(self.vines_objetivo)].copy()
                df_prov['_orden'] = df_prov['AÑO - MES'].map(_orden_periodo)
                df_prov = df_prov.sort_values('_orden').drop_duplicates('VIN', keep='last').drop(columns='_orden')
                self.log_signal.emit(f"[FILTRO] Provisión más reciente de {len(df_prov)} VIN solicitados")
            elif fechas_unicas:
                fechas_ordenadas = sorted(
                    fechas_unicas, 
                    key=lambda f: (
                        int(f.split("-")[0].strip()), 
                        meses_map.get(f.split("-")[1].strip().capitalize(), 0)
                    )
                )
                mes_objetivo = fechas_ordenadas[-1]
                self.log_signal.emit(f"[FILTRO] Cruzando exclusivamente con los VIN de la Provisión: {mes_objetivo}")
                df_prov = df_prov[df_prov['AÑO - MES'] == mes_objetivo].copy()
            else:
                self.log_signal.emit("[ALERTA] No se detectó formato de fecha en Provisiones. Procesando todos los VINs.")
                
            if not self.usar_provision and not self.vines_objetivo:
                df_prov = df_prov.iloc[0:0].copy()

            if self.vines_extra and not self.vines_objetivo:
                nuevos = self.vines_extra - set(df_prov['VIN'])
                if nuevos:
                    previos = df_prov_todo[df_prov_todo['VIN'].isin(nuevos)].copy()
                    previos['_orden'] = previos['AÑO - MES'].map(_orden_periodo)
                    previos = previos.sort_values('_orden').drop_duplicates('VIN', keep='last').drop(columns='_orden')
                    self.vines_sin_provision = nuevos - set(previos['VIN'])
                    sin_prov = pd.DataFrame({'VIN': sorted(self.vines_sin_provision)})
                    for col in ('Cantidad de Meses', 'AÑO - MES', 'CLIENTE', 'OBSERVACIONES'):
                        sin_prov[col] = ""
                    df_prov = pd.concat([df_prov, previos, sin_prov], ignore_index=True)
                    self.log_signal.emit(f"[FILTRO] {len(nuevos)} VIN del RM sumados"
                                         + (f" ({len(self.vines_sin_provision)} sin provisión: sin meses)" if self.vines_sin_provision else ""))

            self.log_signal.emit(f"[INFO] Total VINs a procesar: {len(df_prov)}")

            self.df_comercial['VIN_CLEAN'] = self.df_comercial['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper()

            self.log_signal.emit("[LEYENDO] Conectando con BBDD CLIENTE CM.xlsx (David, cache CSV interno)...")
            df_bbdd = pd.DataFrame()
            if lectura_bbdd is not None:
                df_bbdd = lectura_bbdd.result()
            else:
                self.log_signal.emit("[AVISO] BBDD CLIENTE CM no configurada o no encontrada.")

            self.log_signal.emit("[LEYENDO] Conectando con Contactos.xlsx (Maxi)...")
            df_contactos = pd.DataFrame()
            if lectura_contactos is not None:
                df_contactos = lectura_contactos.result()
                lector.shutdown(wait=False)
            else:
                self.log_signal.emit("[AVISO] Contactos.xlsx no configurado o no encontrado.")

            self.log_signal.emit("[CRUZANDO] Recopilando todos los datos mediante VIN solicitados...")
            
            registros = []
            dict_actualizacion_comercial = {}
            
            hoy = datetime.now()
            fecha_inicio_str = f"01-{hoy.strftime('%m-%Y')}"
            
            from dateutil.relativedelta import relativedelta

            def _limpio(valor):
                v = str(valor).strip()
                return "" if v.lower() in ['nan', 'none', '<na>', '-'] else v

            # Índices armados una sola vez: filtrar los DataFrame completos por cada VIN era lo que más tardaba
            t_lecturas = perf_counter() - t_inicio
            com = self.df_comercial
            if 'ID' in com.columns:
                com = com.assign(_ID=pd.to_numeric(com['ID'], errors='coerce')).sort_values('_ID', na_position='first', kind='stable')
            por_vin = com.drop_duplicates('VIN_CLEAN', keep='last').set_index('VIN_CLEAN')
            lookup_razon = provisiones_services.construir_lookup_razon_social(self.df_comercial)
            bbdd_por_cdb = df_bbdd.set_index('CDB_CLEAN') if 'CDB_CLEAN' in df_bbdd.columns else pd.DataFrame()
            contactos_por_cdb = dict(tuple(df_contactos.groupby('CDB_CLEAN'))) if 'CDB_CLEAN' in df_contactos.columns else {}

            for n_fila, (_, row_prov) in enumerate(df_prov.iterrows()):
                if n_fila % 3 == 0:
                    self.msleep(1)
                vin = row_prov['VIN']
                meses = _formatear_meses(row_prov['Cantidad de Meses'])
                if not meses:
                    # Provisión sin meses: se toman de la observación solo si habla de
                    # un plan Volvo Connect (Blue/Gold/Silver son de CM y no cuentan)
                    meses = provisiones_services.meses_desde_observacion(row_prov.get('OBSERVACIONES', '')) or ""
                cliente_prov = _limpio(row_prov.get('CLIENTE', ''))

                chasis = ""
                rut = ""
                cdb = ""
                razon_comercial = ""

                if vin in por_vin.index:
                    match = por_vin.loc[vin]
                    chasis = str(match.get('CHASIS', '')).strip()
                    rut = _limpio(match.get('RUT', ''))
                    cdb = _limpio(match.get('CDB', '')).replace('.0', '')
                    razon_comercial = _limpio(match.get('RAZÓN SOCIAL', ''))
                else:
                    chasis = vin[-7:] if len(vin) >= 7 else vin

                # Sin el VIN en Comercial (o con datos incompletos) se busca la
                # empresa por el cliente de Provisiones, solo si es inequívoca
                if cliente_prov and not (rut and cdb and razon_comercial):
                    candidatos = provisiones_services.buscar_candidatos_por_cliente(self.df_comercial, cliente_prov, lookup=lookup_razon)
                    combos = {(_limpio(c.get('RAZÓN SOCIAL')), _limpio(c.get('RUT')), _limpio(c.get('CDB')).replace('.0', ''))
                              for c in candidatos if _limpio(c.get('RUT')) or _limpio(c.get('CDB'))}
                    if len(combos) == 1:
                        razon_c, rut_c, cdb_c = next(iter(combos))
                        razon_comercial = razon_comercial or razon_c
                        rut = rut or rut_c
                        cdb = cdb or cdb_c

                razon_social = ""
                direccion = ""
                comuna = ""
                director = {'nombre': '', 'correo': '', 'telefono': ''}

                if cdb and cdb in bbdd_por_cdb.index:
                    b_match = bbdd_por_cdb.loc[cdb]
                    razon_social = _limpio(b_match.get('Nombre', ''))
                    direccion = str(b_match.get('Dirección', '')).strip()
                    comuna = str(b_match.get('Comuna', '')).strip()
                    rut = rut or _limpio(b_match.get('RUT', ''))
                    director = {'nombre': razon_social,
                                'correo': _limpio(b_match.get('Correo electrónico', '')),
                                'telefono': _limpio(str(b_match.get('Teléfono', '')).split('.')[0])}
                razon_social = razon_comercial or razon_social or cliente_prov

                admin_flota = ""
                correo = ""
                telefono = ""

                if cdb and contactos_por_cdb:
                    admin_flota, correo, telefono = _elegir_contacto(contactos_por_cdb.get(cdb))

                # Lo que el administrador de flota no trae se completa con el
                # director de empresa (BBDD CLIENTES CM, un registro por CDB)
                if not admin_flota and (director['correo'] or director['telefono']):
                    admin_flota = "Director de empresa"
                correo = correo or director['correo']
                telefono = telefono or director['telefono']

                nombre_contrato = f"{chasis} {razon_social}".strip()
                
                fecha_termino_str = "Pendiente"
                if meses.upper() in ['-', 'MENSUAL']:
                    fecha_termino_str = "MENSUAL"
                else:
                    try:
                        meses_int = int(float(meses))
                        fecha_ini_dt = pd.to_datetime(fecha_inicio_str, format="%d-%m-%Y")
                        fecha_fin_dt = fecha_ini_dt + relativedelta(months=meses_int)
                        fecha_termino_str = fecha_fin_dt.strftime("%d-%m-%Y")
                    except Exception:
                        pass
                        
                # --- CAMBIO DE NOMBRE DE COLUMNAS AQUÍ ---
                if vin not in self.vines_sin_provision:
                    dict_actualizacion_comercial[vin] = {
                        'VIN': vin,
                        'cambios': {
                            'INICIO': fecha_inicio_str,
                            'TERMINO': fecha_termino_str
                        }
                    }
                
                def _c(val):
                    v = str(val).strip()
                    return "" if v.lower() in ['nan', 'none', '<na>', '0', '0.0'] else v

                registros.append({
                    'RUT': _c(rut),
                    'VIN': _c(vin),
                    'CHASSIS': _c(chasis),
                    'NOMBRE CONTRATO': _c(nombre_contrato),
                    'RAZON SOCIAL': _c(razon_social),
                    'DIRECCIÓN': _c(direccion),
                    'COMUNA': _c(comuna),
                    'ADMINISTRADOR DE FLOTA': _c(admin_flota),
                    'CORREO ADMINISTRADOR': _c(correo),
                    'TELÉFONO ADMINISTRADOR': _c(telefono),
                    'INICIO': fecha_inicio_str,
                    'MESES': meses,
                    'TERMINO': fecha_termino_str
                })
                
            df_resultado = pd.DataFrame(registros)
            logger.info(f"Instalaciones: lecturas {t_lecturas:.1f} s, cruce {perf_counter() - t_inicio - t_lecturas:.1f} s, {len(registros)} VIN")
            
            if df_resultado.empty:
                self.log_signal.emit("[ALERTA] Cruce finalizó con 0 resultados.")
            else:
                df_resultado = df_resultado.drop_duplicates(subset=['VIN'])
                self.log_signal.emit(f"[ÉXITO] Cruce completado. {len(df_resultado)} registros listos para previsualizar.")
            
            self.df_cruzado = df_resultado
            self.preview_signal.emit(df_resultado, dict_actualizacion_comercial)

        except Exception as e:
            self.error_signal.emit(f"Error fatal: {str(e)}")

# =========================================================
# ASISTENTE PARA GENERAR EL MES (dentro de la pantalla de Instalaciones)
# =========================================================
_AZUL_OSCURO = "#1B2B4E"
_QSS_BTN_PRIM = (
    f"QPushButton {{ background: {_AZUL_OSCURO}; color: white; border: none; border-radius: 10px; "
    "padding: 0 18px; min-height: 34px; font-weight: 700; font-size: 12px; }"
    "QPushButton:hover { background: #2C4A80; } QPushButton:disabled { background: #A9B3C4; }")
_QSS_BTN_SEC = (
    f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
    "border-radius: 10px; padding: 0 18px; min-height: 34px; font-weight: 700; font-size: 12px; }"
    "QPushButton:hover { background: #F1F4F9; }")
_QSS_CAMPO = (
    f"QLineEdit {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid #DCE3EC; "
    "border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; font-weight: 600; }"
    f"QLineEdit:focus {{ border: 1px solid {_AZUL_OSCURO}; }}")
_QSS_TABLA_RM = (
    f"QTableWidget {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px; "
    f"outline: none; gridline-color: transparent; color: {estilo_com.TINTA}; font-size: 12px; }}"
    f"QTableWidget::item {{ padding: 0 8px; border-bottom: 1px solid {estilo_com.LINEA_SUAVE}; }}"
    f"QHeaderView::section {{ background: {estilo_com.SUPERFICIE_2}; color: {estilo_com.APAGADO}; border: none; "
    "padding: 6px 8px; font-size: 10px; font-weight: 800; letter-spacing: 1px; }")


class GenerarMesPanel(QWidget):
    """Generar el mes en tres pasos: elegir los VIN, cruzar los datos (con el
    avance por etapas) y revisar el resultado antes de guardar. Se muestra en
    lugar de la tabla de Instalaciones, sin ventana aparte."""
    volver = pyqtSignal(bool)  # True si se guardó una hoja nueva
    MENSAJES_ETAPA = ("Leyendo las provisiones…", "Buscando los directores de empresa…", "Reuniendo los contactos…", "Completando RUT y razón social…")
    PASOS = (("Origen de los VIN", "Qué VIN entran al mes"),
             ("Cruce de datos", "Etapas y avisos"),
             ("Revisión", "Revisar y guardar"))
    _SUBTITULOS = ("Elige qué VIN entran al mes", "Procesando, no cierres la pantalla", "Revisa el resultado antes de guardar")
    _TAGS = {"SISTEMA": "gris", "INFO": "gris", "LEYENDO": "azul", "FILTRO": "violeta", "CRUZANDO": "violeta",
             "AVISO": "ambar", "ALERTA": "ambar", "ÉXITO": "verde"}
    MAX_RESULTADOS = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.df_para_guardar = None
        self.dict_comercial = None
        self.data_manager = DataManager()
        self.vines_extra = []
        self._rm = None
        self._etapa_actual = -1
        self._avisos = set()
        self._meta_avance = 0
        self._valor_avance = 0.0
        self._ticks = 0
        self._t_cruce = perf_counter()
        self._texto_etapa = ""
        self._reloj = QTimer(self)
        self._reloj.setInterval(40)
        self._terminando = False
        self._reloj.timeout.connect(self._animar_avance)
        self._setup_ui()

    # ------------------------------------------------------------ interfaz
    def _setup_ui(self):
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 12, 0, 0)
        raiz.setSpacing(12)
        raiz.addWidget(self._crear_caja_pasos())
        raiz.addWidget(self._crear_caja_contenido(), 1)
        self._ir_a(0)

    def _crear_caja_pasos(self):
        caja = admin_estilo.caja_con_encabezado("cajaPasosMes", "Generar mes", "Instalaciones")
        caja.marco.setFixedWidth(250)
        self._lay_pasos = QVBoxLayout()
        self._lay_pasos.setContentsMargins(14, 14, 14, 6)
        self._lay_pasos.setSpacing(14)
        caja.cuerpo.addLayout(self._lay_pasos)

        bloque_resumen = admin_estilo.bloque_caja("Resumen")
        self.lbl_resumen = admin_listas.texto("", tam=12)
        self.lbl_resumen.setWordWrap(True)
        bloque_resumen.layout().addWidget(self.lbl_resumen)
        caja.cuerpo.addWidget(bloque_resumen)
        caja.cuerpo.addStretch(1)

        bloque_volver = admin_estilo.bloque_caja("Salir")
        self.btn_salir = admin_estilo.boton_accion("Volver", 'fa5s.arrow-left')
        self.btn_salir.clicked.connect(self._cancelar)
        bloque_volver.layout().addWidget(self.btn_salir)
        caja.cuerpo.addWidget(bloque_volver)
        return caja.marco

    def _crear_caja_contenido(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaContenidoMes", "", "")
        self.pila = QStackedWidget()
        self.pila.addWidget(self._pagina_origen())
        self.pila.addWidget(self._pagina_cruce())
        self.pila.addWidget(self._pagina_revision())
        self._caja.cuerpo.addWidget(self.pila, 1)

        pie = QFrame()
        pie.setStyleSheet(f"QFrame {{ background: {estilo_com.SUPERFICIE_2}; border: none; border-top: 1px solid {estilo_com.LINEA}; }}")
        fila_pie = QHBoxLayout(pie)
        fila_pie.setContentsMargins(16, 10, 16, 10)
        fila_pie.addStretch()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setStyleSheet(_QSS_BTN_SEC)
        self.btn_cancel.clicked.connect(self._cancelar)
        self.btn_back = QPushButton("Volver")
        self.btn_back.setStyleSheet(_QSS_BTN_SEC)
        self.btn_back.clicked.connect(lambda: self._ir_a(0))
        self.btn_start = QPushButton("Iniciar cruce")
        self.btn_start.setStyleSheet(_QSS_BTN_PRIM)
        self.btn_start.clicked.connect(self.start_sync)
        self.btn_inject = QPushButton("Aprobar y guardar")
        self.btn_inject.setStyleSheet(_QSS_BTN_PRIM)
        self.btn_inject.clicked.connect(self.save_data)
        for b in (self.btn_cancel, self.btn_back, self.btn_start, self.btn_inject):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            fila_pie.addWidget(b)
        self._caja.cuerpo.addWidget(pie)
        return self._caja.marco

    def _tarjeta(self, titulo):
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaMes")
        tarjeta.setStyleSheet(f"QFrame#tarjetaMes {{ background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        lay.addWidget(admin_listas.texto(titulo, tam=13, negrita=True))
        return tarjeta, lay

    def _pagina_origen(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        tarjeta_prov, l1 = self._tarjeta("Provisión más reciente")
        self.chk_prov = QCheckBox("Incluir los VIN de la provisión más reciente")
        self.chk_prov.setChecked(True)
        self.chk_prov.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_prov.setStyleSheet(_QSS_CHECK_SERVICIO)
        self.chk_prov.toggled.connect(self._actualizar_resumen_origen)
        l1.addWidget(self.chk_prov)
        descripcion = admin_listas.texto("Toma el último mes de la hoja Prov, como hace hoy «Generar mes».",
                                         color=estilo_com.APAGADO, tam=12)
        descripcion.setWordWrap(True)
        l1.addWidget(descripcion)
        lay.addWidget(tarjeta_prov)

        tarjeta_rm, l2 = self._tarjeta("Sumar VIN del RM")
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setStyleSheet(_QSS_CAMPO)
        self.txt_buscar.setPlaceholderText("Buscar por VIN, chasis, razón social o RUT")
        self.txt_buscar.textChanged.connect(self._buscar_vin)
        l2.addWidget(self.txt_buscar)

        columnas = QHBoxLayout()
        columnas.setSpacing(12)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(6)
        self.lbl_estado_rm = admin_listas.texto("", color=estilo_com.APAGADO, tam=12, negrita=True)
        izquierda.addWidget(self.lbl_estado_rm)
        self.tabla_rm = self._crear_tabla_rm(["", "VIN", "CHASIS", "RAZÓN SOCIAL", "RUT"], (0, 1, 2, 4), (34, 170, 90, 100), 3)
        self.tabla_rm.cellClicked.connect(self._alternar_fila_rm)
        self.tabla_rm.hide()
        izquierda.addWidget(self.tabla_rm, 1)
        izquierda.addStretch(0)
        columnas.addLayout(izquierda, 3)

        derecha = QVBoxLayout()
        derecha.setSpacing(6)
        self.lbl_agregados = admin_listas.texto("Ningún VIN del RM agregado.", color=estilo_com.APAGADO, tam=12, negrita=True)
        derecha.addWidget(self.lbl_agregados)
        self.tabla_sel = self._crear_tabla_rm(["VIN", "RAZÓN SOCIAL"], (0,), (170,), 1)
        self.tabla_sel.cellClicked.connect(self._quitar_fila_sel)
        self.tabla_sel.setToolTip("Clic en una fila para quitarla")
        self.tabla_sel.hide()
        derecha.addWidget(self.tabla_sel, 1)
        self.lbl_vacio_sel = admin_listas.texto("Los VIN que elijas a la izquierda aparecerán aquí. Clic en uno para quitarlo.",
                                                color=estilo_com.APAGADO, tam=12)
        self.lbl_vacio_sel.setWordWrap(True)
        self.lbl_vacio_sel.setAlignment(Qt.AlignmentFlag.AlignTop)
        derecha.addWidget(self.lbl_vacio_sel, 1)
        columnas.addLayout(derecha, 2)
        l2.addLayout(columnas, 1)
        lay.addWidget(tarjeta_rm, 1)
        self._buscar_vin("")
        return pagina

    def _crear_tabla_rm(self, titulos, fijas, anchos, estirada):
        tabla = QTableWidget(0, len(titulos))
        tabla.setHorizontalHeaderLabels(titulos)
        tabla.setStyleSheet(_QSS_TABLA_RM)
        tabla.verticalHeader().hide()
        tabla.verticalHeader().setDefaultSectionSize(34)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setShowGrid(False)
        tabla.setCursor(Qt.CursorShape.PointingHandCursor)
        tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabla.setTextElideMode(Qt.TextElideMode.ElideRight)
        cab = tabla.horizontalHeader()
        cab.setSectionResizeMode(estirada, QHeaderView.ResizeMode.Stretch)
        for col, ancho in zip(fijas, anchos):
            cab.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            tabla.setColumnWidth(col, ancho)
        return tabla

    def _pagina_cruce(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.addStretch(1)
        base = ThemeManager.icon('fa5s.sync-alt', color=_AZUL_OSCURO).pixmap(34, 34)
        self._fotogramas = []
        for grados in range(0, 360, 15):
            girado = base.transformed(QTransform().rotate(grados), Qt.TransformationMode.SmoothTransformation)
            self._fotogramas.append(girado.copy((girado.width() - 34) // 2, (girado.height() - 34) // 2, 34, 34))
        self._pix_giro = base
        self.icono_giro = QLabel()
        self.icono_giro.setFixedHeight(46)
        self.icono_giro.setPixmap(self._pix_giro)
        self.icono_giro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icono_giro.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.icono_giro)
        lay.addSpacing(10)
        titulo = admin_listas.texto("Cargando los datos, espera un momento", tam=18, negrita=True)
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(titulo)
        self.lbl_etapa = admin_listas.texto("", color=estilo_com.APAGADO, tam=13)
        self.lbl_etapa.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_etapa)
        lay.addSpacing(14)
        self.barra_avance = QProgressBar()
        self.barra_avance.setRange(0, 1000)
        self.barra_avance.setTextVisible(False)
        self.barra_avance.setFixedHeight(8)
        self.barra_avance.setFixedWidth(480)
        self.barra_avance.setStyleSheet(
            f"QProgressBar {{ background: {estilo_com.LINEA_SUAVE}; border: none; border-radius: 4px; }}"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1B2B4E, stop:1 #2C4A80); border-radius: 4px; }")
        lay.addWidget(self.barra_avance, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(6)
        self.lbl_avisos = admin_listas.texto("", color="#D98404", tam=12, negrita=True)
        self.lbl_avisos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_avisos)
        self.lbl_tiempo = admin_listas.texto("", color=estilo_com.APAGADO, tam=11)
        self.lbl_tiempo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_tiempo)
        lay.addStretch(2)
        self._pintar_etapas()
        return pagina

    def _pagina_revision(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        self.fila_resumen = QHBoxLayout()
        self.fila_resumen.setSpacing(8)
        lay.addLayout(self.fila_resumen)

        fila_nombre = QHBoxLayout()
        fila_nombre.setSpacing(10)
        fila_nombre.addWidget(admin_listas.texto("Nombre de la hoja nueva", color=estilo_com.APAGADO, tam=12, negrita=True))
        self.txt_nombre = QLineEdit()
        self.txt_nombre.setStyleSheet(_QSS_CAMPO)
        self.txt_nombre.setPlaceholderText("Ej: noviembre")
        self.txt_nombre.setMaximumWidth(280)
        self.txt_nombre.textChanged.connect(lambda _t: self.lbl_aviso_nombre.setText(""))
        fila_nombre.addWidget(self.txt_nombre)
        self.lbl_aviso_nombre = admin_listas.texto("", color="#D98404", tam=12, negrita=True)
        fila_nombre.addWidget(self.lbl_aviso_nombre, 1)
        lay.addLayout(fila_nombre)

        self.preview_table = VolvoTableWidget()
        self.preview_table.menu_type = "general"  # solo lectura: sin "Eliminar Camión"
        self.preview_model = PandasTableModel()
        self.preview_table.setModel(self.preview_model)
        lay.addWidget(self.preview_table, 1)
        return pagina

    # ------------------------------------------------------------ pasos
    def _ir_a(self, paso):
        self.pila.setCurrentIndex(paso)
        self._caja.lbl_titulo.setText(f"{paso + 1} · {self.PASOS[paso][0]}")
        self._caja.lbl_subtitulo.setText(self._SUBTITULOS[paso])
        while self._lay_pasos.count():
            item = self._lay_pasos.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, (nombre, detalle) in enumerate(self.PASOS):
            hecho, actual = i < paso, i == paso
            fondo = estilo_com.VERDE if hecho else (_AZUL_OSCURO if actual else "#EEF2F6")
            color = "white" if hecho or actual else estilo_com.APAGADO
            fila = QWidget()
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            punto = QLabel("✓" if hecho else str(i + 1))
            punto.setFixedSize(26, 26)
            punto.setAlignment(Qt.AlignmentFlag.AlignCenter)
            punto.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 13px; font-size: 12px; font-weight: 800;")
            textos = QVBoxLayout()
            textos.setSpacing(0)
            textos.addWidget(admin_listas.texto(nombre, tam=12, negrita=True))
            textos.addWidget(admin_listas.texto(detalle, color=estilo_com.APAGADO, tam=11))
            lay.addWidget(punto)
            lay.addLayout(textos, 1)
            self._lay_pasos.addWidget(fila)
        if paso == 1:
            self._reloj.start()
        else:
            self._reloj.stop()
        self.btn_start.setVisible(paso == 0)
        self.btn_cancel.setVisible(paso != 2)
        self.btn_back.setVisible(paso == 2)
        self.btn_inject.setVisible(paso == 2)
        if paso == 0:
            self._actualizar_resumen_origen()
        elif paso == 1:
            self.lbl_resumen.setText("Cruzando los datos…")
        else:
            self.lbl_resumen.setText("Se guardará como hoja nueva y actualizará INICIO y TERMINO en Comercial.")

    def _cancelar(self):
        if self.worker is not None and self.worker.isRunning():
            for senal in (self.worker.log_signal, self.worker.preview_signal, self.worker.error_signal):
                try:
                    senal.disconnect()
                except TypeError:
                    pass
        self.volver.emit(False)

    # ------------------------------------------------------- selección de VIN
    def _cargar_rm(self):
        if self._rm is not None:
            return self._rm
        df = self.data_manager.get_comercial_df()
        if df is None or df.empty or 'VIN' not in df.columns:
            self._rm = pd.DataFrame(columns=['VIN', 'CHASIS', 'RAZÓN SOCIAL', 'RUT', '_buscar'])
            return self._rm
        columnas = [c for c in ('VIN', 'CHASIS', 'RAZÓN SOCIAL', 'RUT') if c in df.columns]
        rm = df[columnas].copy().fillna("").astype(str)
        rm['VIN'] = rm['VIN'].str.replace(r'\s+', '', regex=True).str.upper()
        for c in ('CHASIS', 'RAZÓN SOCIAL', 'RUT'):
            if c not in rm.columns:
                rm[c] = ""
        rm = rm[rm['VIN'] != ""].drop_duplicates('VIN')
        rm['_buscar'] = (rm['VIN'] + " " + rm['CHASIS'] + " " + rm['RAZÓN SOCIAL'] + " " + rm['RUT']).str.lower()
        self._rm = rm.reset_index(drop=True)
        return self._rm

    def _buscar_vin(self, texto):
        self.tabla_rm.setRowCount(0)
        texto = texto.strip().lower()
        if len(texto) < 3:
            self.lbl_estado_rm.setText("Escribe al menos 3 caracteres para buscar en el RM.")
            self.tabla_rm.hide()
            return
        rm = self._cargar_rm()
        coincidencias = rm[rm['_buscar'].str.contains(texto, regex=False)]
        if coincidencias.empty:
            self.lbl_estado_rm.setText("Ningún VIN del RM coincide.")
            self.tabla_rm.hide()
            return
        if len(coincidencias) > self.MAX_RESULTADOS:
            self.lbl_estado_rm.setText(f"Hay {len(coincidencias)} coincidencias: se muestran {self.MAX_RESULTADOS}. Afina la búsqueda.")
        else:
            self.lbl_estado_rm.setText(f"{admin_listas.plural(len(coincidencias), 'coincidencia')}. Haz clic en una fila para agregarla.")
        self.tabla_rm.show()
        filas = coincidencias.head(self.MAX_RESULTADOS)
        self.tabla_rm.setRowCount(len(filas))
        for r, (_, f) in enumerate(filas.iterrows()):
            marca = QTableWidgetItem("")
            marca.setData(Qt.ItemDataRole.UserRole, f['VIN'])
            marca.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabla_rm.setItem(r, 0, marca)
            for c, clave in enumerate(('VIN', 'CHASIS', 'RAZÓN SOCIAL', 'RUT'), start=1):
                celda = QTableWidgetItem(f[clave])
                if c == 1:
                    celda.setForeground(QColor(estilo_com.APAGADO))
                self.tabla_rm.setItem(r, c, celda)
        self._repintar_marcas()

    def _repintar_marcas(self):
        for r in range(self.tabla_rm.rowCount()):
            marca = self.tabla_rm.item(r, 0)
            agregado = marca.data(Qt.ItemDataRole.UserRole) in self.vines_extra
            marca.setText("✓" if agregado else "")
            marca.setForeground(QColor("#0F9D6E"))
            fondo = QColor("#E3F6EE") if agregado else QColor(0, 0, 0, 0)
            for c in range(self.tabla_rm.columnCount()):
                self.tabla_rm.item(r, c).setBackground(fondo)

    def _alternar_fila_rm(self, fila, _columna):
        marca = self.tabla_rm.item(fila, 0)
        if marca is None:
            return
        vin = marca.data(Qt.ItemDataRole.UserRole)
        if vin in self.vines_extra:
            self.vines_extra.remove(vin)
        else:
            self.vines_extra.append(vin)
        self._repintar_marcas()
        self._repintar_seleccion()

    def _quitar_fila_sel(self, fila, _columna):
        item = self.tabla_sel.item(fila, 0)
        if item is None:
            return
        vin = item.data(Qt.ItemDataRole.UserRole)
        if vin in self.vines_extra:
            self.vines_extra.remove(vin)
        self._repintar_marcas()
        self._repintar_seleccion()

    def _repintar_seleccion(self):
        rm = self._cargar_rm().set_index('VIN')
        self.tabla_sel.setRowCount(len(self.vines_extra))
        for r, vin in enumerate(self.vines_extra):
            detalle = rm.loc[vin, 'RAZÓN SOCIAL'] if vin in rm.index else ""
            vin_item = QTableWidgetItem(vin)
            vin_item.setData(Qt.ItemDataRole.UserRole, vin)
            vin_item.setForeground(QColor(estilo_com.APAGADO))
            self.tabla_sel.setItem(r, 0, vin_item)
            self.tabla_sel.setItem(r, 1, QTableWidgetItem(detalle))
        n = len(self.vines_extra)
        self.lbl_agregados.setText(admin_listas.plural(n, "VIN agregado") + " del RM" if n else "Ningún VIN del RM agregado.")
        self.tabla_sel.setVisible(n > 0)
        self.lbl_vacio_sel.setVisible(n == 0)
        self._actualizar_resumen_origen()

    def _actualizar_resumen_origen(self, *_):
        if self.pila.currentIndex() != 0:
            return
        partes = []
        if self.chk_prov.isChecked():
            partes.append("VIN de la provisión más reciente")
        if self.vines_extra:
            partes.append(admin_listas.plural(len(self.vines_extra), "VIN") + " del RM")
        self.lbl_resumen.setText(" + ".join(partes) if partes else "Elige al menos un origen de VIN.")
        self.btn_start.setEnabled(bool(partes))

    # ------------------------------------------------------------ cruce
    def _pintar_etapas(self, actual=-1, avisos=(), terminado=False):
        if terminado:
            mensaje, self._meta_avance = "Datos listos, preparando la revisión…", 100
        elif actual >= 0:
            mensaje = self.MENSAJES_ETAPA[actual]
            self._meta_avance = 8 + actual * 22
        else:
            mensaje, self._meta_avance = "Preparando el cruce…", 4
        self._texto_etapa = mensaje.rstrip('.…')
        self.lbl_etapa.setText(mensaje)
        n = len(avisos)
        self.lbl_avisos.setText(f"{admin_listas.plural(n, 'aviso')} por revisar al final" if n else "")

    def _animar_avance(self):
        # Acerca la barra a su meta de a poco y la deja avanzando lento dentro de la etapa
        actual = self._valor_avance
        tope = self._meta_avance + (18 if self._meta_avance < 100 else 0)
        if actual < self._meta_avance:
            actual += max(3.0 if self._terminando else 0.15, (self._meta_avance - actual) * 0.05)
        elif actual < tope and self._meta_avance < 100:
            actual += 0.04
        self._valor_avance = min(actual, 100.0)
        self.barra_avance.setValue(int(self._valor_avance * 10))
        # Ícono girando, puntos que se mueven y segundos transcurridos: muestran que sigue trabajando
        self._ticks += 1
        self.icono_giro.setPixmap(self._fotogramas[self._ticks % len(self._fotogramas)])
        if self._ticks % 8 == 0:
            self.lbl_etapa.setText(self._texto_etapa + "." * (1 + (self._ticks // 8) % 3))
            self.lbl_tiempo.setText(f"Tiempo transcurrido: {int(perf_counter() - self._t_cruce)} s")
        if self._terminando and self._valor_avance >= 100:
            self._terminando = False
            self._ir_a(2)

    def write_log(self, text):
        etiqueta, _, resto = text.partition("]")
        etiqueta = etiqueta.lstrip("[").strip().upper()
        etapa = None
        if "Extrayendo VINs" in text:
            etapa = 0
        elif "BBDD CLIENTE" in text:
            etapa = 1
        elif "Contactos.xlsx" in text and "Conectando" in text:
            etapa = 2
        elif etiqueta == "CRUZANDO":
            etapa = 3
        if etapa is not None and etapa > self._etapa_actual:
            self._etapa_actual = etapa
        if etiqueta in ("AVISO", "ALERTA") and self._etapa_actual >= 0:
            self._avisos.add(self._etapa_actual)
        self._pintar_etapas(self._etapa_actual, self._avisos, terminado=etiqueta == "ÉXITO")

    def start_sync(self):
        self._etapa_actual = -1
        self._avisos = set()
        self._valor_avance = 0.0
        self._terminando = False
        self._t_cruce = perf_counter()
        self.barra_avance.setValue(0)
        self._pintar_etapas()
        self._ir_a(1)
        self.btn_start.setEnabled(False)

        df_comercial = self.data_manager.get_comercial_df()
        self.worker = InstalacionesSyncWorker(
            df_comercial, vines_extra=self.vines_extra, usar_provision=self.chk_prov.isChecked())
        self.worker.log_signal.connect(self.write_log)
        self.worker.preview_signal.connect(self.show_preview)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.start()

    def show_preview(self, df_resultado, dict_comercial):
        self.df_para_guardar = df_resultado
        self.dict_comercial = dict_comercial
        self.preview_model.set_data(df_resultado)

        while self.fila_resumen.count():
            item = self.fila_resumen.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        total = len(df_resultado)
        sin_correo = int((df_resultado['CORREO ADMINISTRADOR'].astype(str).str.strip() == "").sum()) if total and 'CORREO ADMINISTRADOR' in df_resultado.columns else 0
        sin_meses = int((df_resultado['MESES'].astype(str).str.strip() == "").sum()) if total and 'MESES' in df_resultado.columns else 0
        self.fila_resumen.addWidget(admin_listas.pildora(admin_listas.plural(total, "instalación", "instalaciones"), "azul"))
        self.fila_resumen.addWidget(admin_listas.pildora(f"{sin_correo} sin correo", "ambar" if sin_correo else "verde"))
        self.fila_resumen.addWidget(admin_listas.pildora(f"{sin_meses} sin meses", "ambar" if sin_meses else "verde"))
        sin_provision = len(getattr(self.worker, 'vines_sin_provision', ()) or ())
        if sin_provision:
            self.fila_resumen.addWidget(admin_listas.pildora(f"{sin_provision} sin provisión (no se tocan las fechas en Comercial)", "gris"))
        self.fila_resumen.addStretch()
        self.txt_nombre.setText(self._nombre_sugerido())
        self.lbl_aviso_nombre.setText("")
        self._terminando = True
        self._pintar_etapas(self._etapa_actual, self._avisos, terminado=True)

    _MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
              "septiembre", "octubre", "noviembre", "diciembre")

    @staticmethod
    def _nombre_unico(base, existentes):
        """Con un nombre repetido agrega (1), (2)… sin pasar los 31 caracteres que admite una hoja."""
        base = base[:31]
        if base not in existentes:
            return base
        n = 1
        while True:
            sufijo = f" ({n})"
            candidato = base[:31 - len(sufijo)] + sufijo
            if candidato not in existentes:
                return candidato
            n += 1

    def _nombre_sugerido(self):
        hoy = datetime.now()
        base = f"{self._MESES[hoy.month - 1].capitalize()} - {hoy.year}"
        existentes = []
        if os.path.exists(INSTALACIONES_PATH):
            try:
                with pd.ExcelFile(INSTALACIONES_PATH) as xls:
                    existentes = list(xls.sheet_names)
            except Exception as e:
                logger.warning(f"No se pudieron leer las hojas de Instalaciones: {e}")
        return self._nombre_unico(base, existentes)

    def handle_error(self, error_msg):
        QMessageBox.critical(self, "Error Fatal", error_msg)
        self.btn_start.setEnabled(True)
        self._ir_a(0)

    def save_data(self):
        if self.df_para_guardar is None or self.df_para_guardar.empty:
            QMessageBox.warning(self, "Error", "No hay datos para guardar.")
            return

        nombre_hoja = self.txt_nombre.text().strip()
        if not nombre_hoja:
            self.lbl_aviso_nombre.setText("Escribe el nombre de la hoja nueva.")
            self.txt_nombre.setFocus()
            return

        try:
            import openpyxl
            from openpyxl.utils.dataframe import dataframe_to_rows

            if os.path.exists(INSTALACIONES_PATH):
                wb = openpyxl.load_workbook(INSTALACIONES_PATH)
                nombre_hoja = self._nombre_unico(nombre_hoja, wb.sheetnames)

            _mostrar_velo(self, f"Guardando '{nombre_hoja}' en Instalaciones…")
            writer_backup = ExcelWriter()
            writer_backup._crear_backup(INSTALACIONES_PATH)
            if not writer_backup.last_backup_ok:
                terminar_guardando(self, exito=False)
                QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad de Instalaciones.xlsx. La operación fue cancelada y no se realizó ningún cambio.")
                return

            if not os.path.exists(INSTALACIONES_PATH):
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = nombre_hoja
            else:
                if nombre_hoja in wb.sheetnames:
                    wb.remove(wb[nombre_hoja])
                ws = wb.create_sheet(nombre_hoja)

            for r in dataframe_to_rows(self.df_para_guardar, index=False, header=True):
                ws.append(r)

            wb.save(INSTALACIONES_PATH)

        # --- INYECCIÓN HACIA COMERCIAL (PruebasFM) ---
            if self.dict_comercial:
                writer = ExcelWriter()
                writer.update_cells(self.dict_comercial, module_name="Auto-Instalaciones")
                self.data_manager.load_data_async()

            mensaje_exito = f"Datos guardados exitosamente en la hoja '{nombre_hoja}' de Instalaciones.\nFechas de facturación actualizadas en Comercial."
            if not writer_backup.last_backup_ok:
                mensaje_exito += "\n\n⚠️ Aviso: no se pudo crear la copia de seguridad previa de Instalaciones.xlsx."
            terminar_guardando(self, texto_exito="Mes guardado")
            if not writer_backup.last_backup_ok:
                QMessageBox.warning(self, "Aviso", mensaje_exito)
            self.volver.emit(True)

        except PermissionError:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", "El archivo Instalaciones.xlsx está abierto. Ciérralo y vuelve a intentar.")
        except Exception as e:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error al guardar", str(e))


# =========================================================
# LA PESTAÑA PRINCIPAL
# =========================================================
class InstalacionesModule(QWidget):
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.df_base = pd.DataFrame()

        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()
        self.load_local_data()

    def _setup_ui(self):
        main_layout = admin_estilo.raiz_pantalla(self)

        cuerpo = QWidget()
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(12)
        fila.addWidget(self._crear_caja_hojas())
        fila.addWidget(self._crear_caja_tabla(), 1)
        self._pila = QStackedWidget()
        self._pila.addWidget(cuerpo)
        main_layout.addWidget(self._pila, 1)

    def _crear_caja_hojas(self):
        caja = admin_estilo.caja_con_encabezado("cajaHojasInstalaciones", "Instalaciones", "Hojas por mes")
        caja.marco.setFixedWidth(250)
        lay = caja.cuerpo

        bloque_hoja = admin_estilo.bloque_caja("Hoja")
        self.combo_mes = estilo_com.ComboTarjeta("Hoja (mes)")
        self.combo_mes.addItem("Sin datos...")
        self.combo_mes.currentTextChanged.connect(self.change_sheet)
        self.combo_mes.setStyleSheet(_ESTILO_COMBO)
        self.combo_mes.setCursor(Qt.CursorShape.PointingHandCursor)
        bloque_hoja.layout().addWidget(self.combo_mes)
        lay.addWidget(bloque_hoja)

        bloque_acciones = admin_estilo.bloque_caja("Acciones")
        self.btn_generar = admin_estilo.boton_accion("Generar mes", 'fa5s.cogs')
        self.btn_generar.clicked.connect(self.open_sync_dialog)
        self.btn_renombrar = admin_estilo.boton_accion("Renombrar hoja", 'fa5s.edit')
        self.btn_renombrar.clicked.connect(self.rename_current_sheet)
        self.btn_export_excel = admin_estilo.boton_accion("Exportar a Excel", 'fa5s.file-excel')
        self.btn_export_excel.clicked.connect(self._exportar_excel)
        self.btn_eliminar = admin_estilo.boton_accion("Eliminar hoja", 'fa5s.trash-alt', peligro=True)
        self.btn_eliminar.clicked.connect(self.delete_current_sheet)
        bloque_acciones.layout().addWidget(self.btn_generar)
        bloque_acciones.layout().addWidget(self.btn_renombrar)
        bloque_acciones.layout().addWidget(self._crear_panel_renombrar())
        bloque_acciones.layout().addWidget(self.btn_export_excel)
        bloque_acciones.layout().addWidget(self.btn_eliminar)
        lay.addWidget(bloque_acciones)
        lay.addStretch(1)
        return caja.marco

    def _crear_panel_renombrar(self):
        self.panel_renombrar = QFrame()
        self.panel_renombrar.setObjectName("panelRenombrar")
        self.panel_renombrar.setStyleSheet(
            f"QFrame#panelRenombrar {{ background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px; }}")
        lay = QVBoxLayout(self.panel_renombrar)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.lbl_renombrar = admin_listas.texto("", tam=11, negrita=True)
        self.lbl_renombrar.setWordWrap(True)
        self.txt_nuevo_nombre = QLineEdit()
        self.txt_nuevo_nombre.setStyleSheet(_QSS_CAMPO)
        self.txt_nuevo_nombre.returnPressed.connect(self._guardar_renombre)
        self.txt_nuevo_nombre.textChanged.connect(lambda _t: self.lbl_error_renombre.setText(""))
        self.lbl_error_renombre = admin_listas.texto("", color="#B3261E", tam=11, negrita=True)
        self.lbl_error_renombre.setWordWrap(True)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        btn_ok = QPushButton("Guardar")
        btn_ok.setStyleSheet(_QSS_BTN_PRIM.replace("0 18px", "0 6px"))
        btn_ok.clicked.connect(self._guardar_renombre)
        btn_no = QPushButton("Cancelar")
        btn_no.setStyleSheet(_QSS_BTN_SEC.replace("0 18px", "0 6px"))
        btn_no.clicked.connect(self.panel_renombrar.hide)
        for b in (btn_ok, btn_no):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            fila.addWidget(b)
        for w in (self.lbl_renombrar, self.txt_nuevo_nombre, self.lbl_error_renombre):
            lay.addWidget(w)
        lay.addLayout(fila)
        self.panel_renombrar.hide()
        return self.panel_renombrar

    def _crear_caja_tabla(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaTablaInstalaciones", "Instalaciones", "")
        self.table = VolvoTableWidget()
        self.table.menu_type = "general"  # Instalaciones no tiene "Eliminar Camión"
        self.table.sort_changed.connect(self.filter_table)
        self.model = ModeloTablaIngresos(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model.set_data(pd.DataFrame(columns=self._COLUMNAS_TABLA))
        self.table.set_model_and_delegate(self.model)
        admin_estilo.estilar_tabla(self.table)
        self._caja.cuerpo.addWidget(self.table, 1)
        return self._caja.marco

    # La tabla muestra lo esencial; el Excel exportado conserva todas las columnas de la hoja
    _COLUMNAS_TABLA = ['RUT', 'RAZON SOCIAL', 'CHASSIS', 'COMUNA', 'ADMINISTRADOR DE FLOTA',
                       'CORREO ADMINISTRADOR', 'INICIO', 'TERMINO']

    def _exportar_excel(self):
        df = getattr(self, '_df_export', None)
        if df is None or df.empty:
            return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
        hoja = self.combo_mes.currentText().strip()
        filepath, _ = QFileDialog.getSaveFileName(self, "Guardar Excel", f"Instalaciones_{hoja}.xlsx", "Archivos Excel (*.xlsx)")
        if filepath:
            from src.ui.compartido.exportacion import iniciar_exportacion
            iniciar_exportacion(self, df, filepath, titulo=f"Instalaciones {hoja}")

    _ANCHOS_COLUMNAS = {
        'RUT': 120, 'RAZON SOCIAL': 240, 'CHASSIS': 110, 'COMUNA': 140, 'ADMINISTRADOR DE FLOTA': 190,
        'CORREO ADMINISTRADOR': 240, 'INICIO': 110, 'TERMINO': 110,
    }

    def _actualizar_kpis(self, df):
        """Título y resumen de la caja según las filas visibles."""
        total = len(df)
        clientes = int(df['RAZON SOCIAL'].astype(str).str.strip().replace("", pd.NA).dropna().nunique()) \
            if not df.empty and 'RAZON SOCIAL' in df.columns else 0
        hoja = self.combo_mes.currentText()
        if hoja and hoja != "Sin datos...":
            self._caja.lbl_titulo.setText(hoja)
            self._caja.lbl_subtitulo.setText(f"{total} instalaciones · {clientes} clientes")
        else:
            self._caja.lbl_titulo.setText("Instalaciones")
            self._caja.lbl_subtitulo.setText("Sin datos")

    def rename_current_sheet(self):
        current_sheet = self.combo_mes.currentText()
        if not current_sheet or current_sheet == "Sin datos...": return
        if self.panel_renombrar.isVisible():
            self.panel_renombrar.hide()
            return
        self.lbl_renombrar.setText(f"Nuevo nombre de «{current_sheet}»")
        self.txt_nuevo_nombre.setText(current_sheet)
        self.lbl_error_renombre.setText("")
        self.panel_renombrar.show()
        self.txt_nuevo_nombre.setFocus()
        self.txt_nuevo_nombre.selectAll()

    def _guardar_renombre(self):
        current_sheet = self.combo_mes.currentText()
        new_name = self.txt_nuevo_nombre.text().strip()
        if not new_name:
            self.lbl_error_renombre.setText("Escribe un nombre.")
            return
        if new_name == current_sheet:
            self.panel_renombrar.hide()
            return
        if new_name != current_sheet:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(INSTALACIONES_PATH)
                if new_name in wb.sheetnames:
                    self.lbl_error_renombre.setText("Ya existe una hoja con ese nombre.")
                    return
                self.panel_renombrar.hide()

                _mostrar_velo(self, "Renombrando la hoja…")
                writer_backup = ExcelWriter()
                writer_backup._crear_backup(INSTALACIONES_PATH)
                if not writer_backup.last_backup_ok:
                    terminar_guardando(self, exito=False)
                    QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad de Instalaciones.xlsx. La operación fue cancelada y no se realizó ningún cambio.")
                    return

                wb[current_sheet].title = new_name
                wb.save(INSTALACIONES_PATH)

                mensaje_exito = f"La hoja se renombró a '{new_name}'."
                if not writer_backup.last_backup_ok:
                    mensaje_exito += "\n\n⚠️ Aviso: no se pudo crear la copia de seguridad previa."
                terminar_guardando(self, texto_exito="Hoja renombrada")
                if not writer_backup.last_backup_ok:
                    QMessageBox.warning(self, "Aviso", mensaje_exito)
                self.load_local_data()
                self.combo_mes.setCurrentText(new_name)

            except PermissionError:
                terminar_guardando(self, exito=False)
                QMessageBox.critical(self, "Error", "El archivo Instalaciones.xlsx está abierto. Ciérralo.")
            except Exception as e:
                terminar_guardando(self, exito=False)
                QMessageBox.critical(self, "Error", str(e))

    def delete_current_sheet(self):
        current_sheet = self.combo_mes.currentText()
        if not current_sheet or current_sheet == "Sin datos...": return
        
        reply = QMessageBox.question(self, "Eliminar Hoja",
                                     f"¿Estás completamente seguro de eliminar la hoja '{current_sheet}'?\nSe creará una copia de seguridad antes de eliminarla, pero la restauración es manual desde Configuración.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(INSTALACIONES_PATH)

                if len(wb.sheetnames) <= 1:
                    QMessageBox.warning(self, "Acción denegada", "No puedes eliminar la única hoja del archivo.\nSi quieres vaciarlo, puedes renombrarla o borrar el archivo desde la carpeta.")
                    return

                _mostrar_velo(self, "Eliminando la hoja…")
                writer_backup = ExcelWriter()
                writer_backup._crear_backup(INSTALACIONES_PATH)
                if not writer_backup.last_backup_ok:
                    terminar_guardando(self, exito=False)
                    QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad de Instalaciones.xlsx. La operación fue cancelada y no se realizó ningún cambio.")
                    return

                del wb[current_sheet]
                wb.save(INSTALACIONES_PATH)

                mensaje_exito = f"La hoja '{current_sheet}' fue eliminada."
                if not writer_backup.last_backup_ok:
                    mensaje_exito += "\n\n⚠️ Aviso: no se pudo crear la copia de seguridad previa."
                terminar_guardando(self, texto_exito="Hoja eliminada")
                if not writer_backup.last_backup_ok:
                    QMessageBox.warning(self, "Aviso", mensaje_exito)
                self.load_local_data()

            except PermissionError:
                terminar_guardando(self, exito=False)
                QMessageBox.critical(self, "Error", "El archivo Instalaciones.xlsx está abierto. Ciérralo.")
            except Exception as e:
                terminar_guardando(self, exito=False)
                QMessageBox.critical(self, "Error", str(e))

    def open_sync_dialog(self):
        if self._pila.count() > 1:
            return
        panel = GenerarMesPanel(self)
        panel.volver.connect(self._cerrar_generar_mes)
        self._pila.addWidget(panel)
        self._pila.setCurrentWidget(panel)

    def _cerrar_generar_mes(self, guardado):
        panel = self._pila.widget(1)
        self._pila.setCurrentIndex(0)
        if panel is not None:
            self._pila.removeWidget(panel)
            panel.deleteLater()
        if guardado:
            self.load_local_data()

    def load_local_data(self):
        try:
            if not os.path.exists(INSTALACIONES_PATH):
                self.combo_mes.blockSignals(True)
                self.combo_mes.clear()
                self.combo_mes.addItem("Sin datos...")
                self.combo_mes.blockSignals(False)
                self.model.set_data(pd.DataFrame())
                self._actualizar_kpis(pd.DataFrame())
                return

            # Un solo ExcelFile: read_excel volvía a abrir y parsear el libro completo
            with pd.ExcelFile(INSTALACIONES_PATH) as xls:
                hojas = xls.sheet_names

                if not hojas:
                    return

                self.combo_mes.blockSignals(True)
                self.combo_mes.clear()
                self.combo_mes.addItems(hojas)
                self.combo_mes.setCurrentText(hojas[-1])
                self.combo_mes.blockSignals(False)

                df_hoja = xls.parse(hojas[-1])
            self.df_base = _meses_sin_decimales(df_hoja.fillna(""))
            self.filter_table()
            
        except Exception as e:
            logger.error(f"Error cargando datos locales de instalaciones: {e}", exc_info=True)

    def change_sheet(self, sheet_name):
        if not sheet_name or sheet_name == "Sin datos..." or not os.path.exists(INSTALACIONES_PATH):
            return
            
        try:
            self.df_base = _meses_sin_decimales(pd.read_excel(INSTALACIONES_PATH, sheet_name=sheet_name).fillna(""))
            self.filter_table()
        except Exception as e:
            logger.warning(f"Error cambiando a la hoja {sheet_name}: {e}")

    def filter_table(self):
        if self.df_base.empty:
            self._df_export = None
            self.model.set_data(pd.DataFrame())
            self._actualizar_kpis(pd.DataFrame())
            return

        search_text = self.search_input.text().lower()
        df_display = self.df_base.copy()
        
        if search_text:
            columnas_busqueda = ['VIN', 'CHASSIS', 'RUT', 'NOMBRE CONTRATO', 'RAZON SOCIAL']
            mask = comercial_services.construir_mascara_busqueda(
                df_display, search_text.strip(), columnas_busqueda)
            df_display = df_display[mask]

        # Ordenamiento tipo Excel elegido por el usuario (no toca el Excel de Instalaciones)
        df_display = self.table.apply_sort(df_display)

        self._df_export = df_display
        df_tabla = df_display[[c for c in self._COLUMNAS_TABLA if c in df_display.columns]]
        self.model.set_data(df_tabla)
        admin_estilo.fijar_columnas(self.table, {c: a for c, a in self._ANCHOS_COLUMNAS.items() if c != 'RAZON SOCIAL'},
                                    'RAZON SOCIAL')
        self._actualizar_kpis(df_display)
