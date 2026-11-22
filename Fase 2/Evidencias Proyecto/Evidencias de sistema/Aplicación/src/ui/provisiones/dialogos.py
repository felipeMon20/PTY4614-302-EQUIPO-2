"""Diálogos de Provisiones: vincular con Comercial, VIN huérfanos y formulario de provisión."""
from src.theme.colors import BACKGROUND, DANGER, PRIMARY, SUCCESS, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY
import pandas as pd
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QLineEdit, QDialog, QTableWidget, QTableWidgetItem, QAbstractItemView, QCheckBox, QHeaderView
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from src.core.excel_writer import ExcelWriter
from src.ui.compartido import comercial_estilo as estilo_com
from src.services import provisiones_services
from src.services import comercial_services
from src.theme.theme_manager import ThemeManager
from src.ui.provisiones.base import (
    MODULE_ACCENT_PROV,
    _PLAN_OPCIONES,
    _construir_registro_nuevo_desde_provisiones,
    _formato_moneda_prov,
)


_QSS_TABLA_VINCULO = (
    "QTableWidget { background: white; border: none; outline: none; font-size: 12px; }"
    "QTableWidget::item { border-top: 1px solid #E5E9F2; padding: 4px 10px; }"
    "QHeaderView::section { background: #F6F8FC; color: #5B6B86; border: none; padding: 8px 10px;"
    " font-size: 10px; font-weight: 700; }")
_QSS_BOTON_NAVY = (
    "QPushButton { background-color: #003057; color: white; border: none; border-radius: 9px;"
    " padding: 9px 18px; font-weight: 700; }"
    "QPushButton:hover { background-color: #0B4276; }"
    "QPushButton:disabled { background-color: #A9B8C9; }")
_QSS_BOTON_CONTORNO = (
    "QPushButton { background-color: white; color: #2563EB; border: 1px solid #2563EB; border-radius: 9px;"
    " padding: 9px 18px; font-weight: 700; }"
    "QPushButton:hover { background-color: #E6EFFD; }")
_CHIPS_ESTADO = {
    'ok': ("Coincide", "#DCFCE7", "#15803D"),
    'varias': ("Elegir cliente", "#FFF4DB", "#7A4B00"),
    'sin': ("Sin coincidencia", "#FEE2E2", "#B91C1C"),
    'sin_cliente': ("Se crea sin cliente", "#FFF4DB", "#7A4B00"),
    'nuevo': ("Contrato nuevo", "#E6EFFD", "#1F6FEB"),
}


def _etiqueta(texto, estilo="", ajustar=True):
    lbl = QLabel(texto)
    lbl.setWordWrap(ajustar)
    lbl.setStyleSheet(f"background: transparent; border: none; {estilo}")
    return lbl


def _clientes_por_vin(data_manager):
    """VIN -> cliente según Provisiones."""
    df = getattr(data_manager, 'df_prov', None)
    if not isinstance(df, pd.DataFrame) or df.empty or 'CLIENTE' not in df.columns or 'VIN' not in df.columns:
        return {}
    vins = df['VIN'].astype(str).str.strip().str.upper()
    return dict(zip(vins, df['CLIENTE'].fillna('').astype(str).str.strip()))


def _plural_camiones(n):
    return f"{n} camión" if n == 1 else f"{n} camiones"


class VincularComercialDialog(QDialog):
    """Vincula con Comercial todos los camiones de Provisiones sin ficha en el Registro Maestro, en una sola
    lista con una fila por cliente: lo que coincide queda listo, lo ambiguo pide elegir un cliente y lo que no
    existe se deja para importar desde Power BI. Con `nuevo_contrato` (VIN con contrato finalizado) crea otro
    contrato de forma Provision heredando el cliente del anterior. Se abre desde VinsHuerfanosAlertDialog (ver
    ProvisionesModule._show_rescue_dialog)."""

    vin_resuelto = pyqtSignal(str)

    def __init__(self, vins_pendientes, data_manager, parent=None, nuevo_contrato=False):
        super().__init__(parent)
        self.nuevo_contrato = nuevo_contrato
        self.setWindowTitle("Crear contratos de Provisión" if nuevo_contrato else "Vincular con Comercial")
        self.resize(940, 640)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        self.data_manager = data_manager
        self.vins_pendientes = list(vins_pendientes)
        self._hilo = None
        self._ya_existen = 0
        self._grupos = self._armar_grupos()
        self._setup_ui()
        self._llenar_tabla()
        self._refrescar_estado()

    # ----------------------------------------------------------- datos
    def _forma_contrato(self):
        return 'Provision' if self.nuevo_contrato else None

    def _armar_grupos(self):
        dm = self.data_manager
        master = dm.df_master
        existentes = set()
        if not self.nuevo_contrato and isinstance(master, pd.DataFrame) and not master.empty and 'VIN' in master.columns:
            existentes = set(master['VIN'].dropna().astype(str).str.strip().str.upper())
        lookup = None if self.nuevo_contrato else provisiones_services.construir_lookup_razon_social(master)
        clientes = {} if self.nuevo_contrato else _clientes_por_vin(dm)
        actuales = dm.get_contratos_actuales_df() if self.nuevo_contrato else None
        grupos = {}
        for vin, cambios in self.vins_pendientes:
            vin = str(vin).strip().upper()
            if vin in existentes:
                self._ya_existen += 1
                continue
            if self.nuevo_contrato:
                fila = provisiones_services.resolver_destino_provision(actuales, vin)['fila']
                candidato = ({c: str(fila.get(c, '') if pd.notna(fila.get(c, '')) else '').strip()
                              for c in ('RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO')} if fila else None)
                cliente = candidato['RAZÓN SOCIAL'] if candidato else ''
                candidatos = [candidato] if candidato else []
            else:
                cliente = clientes.get(vin, '')
                candidatos = provisiones_services.buscar_candidatos_por_cliente(master, cliente, lookup=lookup)
            clave = provisiones_services.normalizar_cliente(cliente) or f"__{vin}"
            grupo = grupos.setdefault(clave, {'cliente': cliente or '(sin cliente en Provisiones)', 'vins': [],
                                              'candidatos': candidatos, 'indice': 0 if len(candidatos) == 1 else None})
            grupo['vins'].append((vin, cambios))
        return list(grupos.values())

    # ------------------------------------------------------------- UI
    def _setup_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 18)
        raiz.setSpacing(14)

        total = sum(len(g['vins']) for g in self._grupos)
        titulo = (f"Crear {_plural_camiones(total)} con contrato nuevo de Provisión" if self.nuevo_contrato
                  else f"Vincular {_plural_camiones(total)} con sus clientes")
        raiz.addWidget(_etiqueta(titulo, "color: #0F1B33; font-size: 19px; font-weight: 800;"))
        texto = ("Estos camiones tienen su contrato finalizado. Se crea un contrato nuevo de forma Provision con el "
                 "mismo cliente del contrato anterior." if self.nuevo_contrato else
                 "Buscamos cada cliente de Provisiones en Comercial. Revisa la lista y crea todos de una vez.")
        if self._ya_existen:
            texto += f" {_plural_camiones(self._ya_existen)} ya existen en Comercial y no se tocan."
        raiz.addWidget(_etiqueta(texto, "color: #5B6B86; font-size: 12px;"))

        fila_cuentas = QHBoxLayout()
        fila_cuentas.setSpacing(10)
        self._cuentas = {}
        for clave, rotulo, color in (('ok', "Con coincidencia", "#15803D"),
                                     ('varias', "Varias opciones, elige una", "#7A4B00"),
                                     ('sin', "Sin coincidencia", "#B91C1C")):
            if self.nuevo_contrato and clave != 'ok':
                continue
            caja = QFrame()
            caja.setObjectName("cuentaVinculo")
            caja.setStyleSheet("QFrame#cuentaVinculo { background: #F6F8FC; border: 1px solid #DDE3EE; border-radius: 12px; }")
            lay = QVBoxLayout(caja)
            lay.setContentsMargins(16, 8, 16, 8)
            lay.setSpacing(0)
            numero = _etiqueta("0", f"color: {color}; font-size: 22px; font-weight: 800;", False)
            lay.addWidget(numero)
            lay.addWidget(_etiqueta(rotulo, "color: #5B6B86; font-size: 11px; font-weight: 600;", False))
            fila_cuentas.addWidget(caja)
            self._cuentas[clave] = numero
        fila_cuentas.addStretch(1)
        raiz.addLayout(fila_cuentas)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["CLIENTE EN PROVISIONES", "CAMIONES", "CLIENTE EN COMERCIAL", "ESTADO"])
        self.tabla.setStyleSheet(_QSS_TABLA_VINCULO)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        cab = self.tabla.horizontalHeader()
        cab.setStretchLastSection(False)
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        cab.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(1, 90)
        self.tabla.setColumnWidth(3, 170)
        marco = QFrame()
        marco.setObjectName("marcoTablaVinculo")
        marco.setStyleSheet("QFrame#marcoTablaVinculo { background: white; border: 1px solid #DDE3EE; border-radius: 12px; }")
        lay_marco = QVBoxLayout(marco)
        lay_marco.setContentsMargins(1, 1, 1, 1)
        lay_marco.addWidget(self.tabla)
        raiz.addWidget(marco, 1)

        self.aviso = QFrame()
        self.aviso.setObjectName("avisoVinculo")
        self.aviso.setStyleSheet(
            "QFrame#avisoVinculo { background: #FFF4DB; border: 1px solid #F2C46B; border-radius: 12px; }"
            "QFrame#avisoVinculo QLabel, QFrame#avisoVinculo QCheckBox { background: transparent; border: none; color: #7A4B00; }")
        lay_aviso = QVBoxLayout(self.aviso)
        lay_aviso.setContentsMargins(14, 10, 14, 10)
        lay_aviso.setSpacing(4)
        self.lbl_aviso = _etiqueta("", "font-size: 13px; font-weight: 800;")
        lay_aviso.addWidget(self.lbl_aviso)
        lay_aviso.addWidget(_etiqueta(
            "Importa sus unidades desde Power BI para traer cliente, RUT y ejecutivo. Si los creas ahora, quedan sin "
            "cliente y marcados para revisión manual.", "font-size: 12px;"))
        self.chk_sin_cliente = QCheckBox("Crear también los camiones sin coincidencia, sin cliente")
        self.chk_sin_cliente.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.chk_sin_cliente.toggled.connect(self._refrescar_estado)
        lay_aviso.addWidget(self.chk_sin_cliente)
        raiz.addWidget(self.aviso)

        self.lbl_pie = _etiqueta("", "color: #5B6B86; font-size: 12px; font-weight: 600;")
        raiz.addWidget(self.lbl_pie)
        pie = QHBoxLayout()
        pie.setSpacing(10)
        pie.addStretch(1)
        self.btn_cerrar = QPushButton("Cerrar")
        ThemeManager.apply_secondary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.close)
        pie.addWidget(self.btn_cerrar)
        self.btn_importar = QPushButton("Importar desde Power BI")
        self.btn_importar.setStyleSheet(_QSS_BOTON_CONTORNO)
        self.btn_importar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_importar.clicked.connect(self._importar_power_bi)
        self.btn_importar.setVisible(not self.nuevo_contrato)
        pie.addWidget(self.btn_importar)
        self.btn_confirmar = QPushButton("Crear en el Registro Maestro")
        self.btn_confirmar.setStyleSheet(_QSS_BOTON_NAVY)
        self.btn_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirmar.clicked.connect(self._confirmar)
        pie.addWidget(self.btn_confirmar)
        raiz.addLayout(pie)

    def _llenar_tabla(self):
        self.tabla.setRowCount(len(self._grupos))
        self._chips = []
        self._combos = {}
        for fila, grupo in enumerate(self._grupos):
            item = QTableWidgetItem(grupo['cliente'])
            fuente = item.font()
            fuente.setBold(True)
            item.setFont(fuente)
            self.tabla.setItem(fila, 0, item)
            n = QTableWidgetItem(str(len(grupo['vins'])))
            n.setToolTip("\n".join(v for v, _ in grupo['vins']))
            self.tabla.setItem(fila, 1, n)
            candidatos = grupo['candidatos']
            if len(candidatos) > 1:
                combo = estilo_com.ComboTarjeta("Elegir cliente")
                combo.addItems(["Elegir cliente…"] + [
                    f"{c.get('RAZÓN SOCIAL', '')}  ·  {c.get('RUT', '') or '-'}  ·  {c.get('CDB', '') or '-'}" for c in candidatos])
                combo.setMinimumWidth(280)
                combo.currentIndexChanged.connect(lambda i, f=fila: self._elegir(f, i))
                self.tabla.setCellWidget(fila, 2, combo)
                self._combos[fila] = combo
            else:
                texto = (f"{candidatos[0].get('RAZÓN SOCIAL', '')}  ·  RUT {candidatos[0].get('RUT', '') or '-'}"
                         if candidatos else "No existe en Comercial")
                self.tabla.setItem(fila, 2, QTableWidgetItem(texto))
            chip = QLabel()
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            contenedor = QFrame()
            contenedor.setStyleSheet("background: transparent;")
            lay = QHBoxLayout(contenedor)
            lay.setContentsMargins(6, 0, 6, 0)
            lay.addWidget(chip)
            self.tabla.setCellWidget(fila, 3, contenedor)
            self._chips.append(chip)

    def _elegir(self, fila, indice):
        self._grupos[fila]['indice'] = indice - 1 if indice > 0 else None
        self._refrescar_estado()

    def _estado_grupo(self, grupo):
        n = len(grupo['candidatos'])
        if grupo['indice'] is not None:
            return 'nuevo' if self.nuevo_contrato else 'ok'
        if n > 1:
            return 'varias'
        return 'sin_cliente' if self.chk_sin_cliente.isChecked() else 'sin'

    def _refrescar_estado(self, *_):
        cuentas = {'ok': 0, 'varias': 0, 'sin': 0}
        a_crear = 0
        sin_coincidencia = 0
        for grupo, chip in zip(self._grupos, self._chips):
            estado = self._estado_grupo(grupo)
            texto, fondo, color = _CHIPS_ESTADO[estado]
            chip.setText(texto)
            chip.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 11px; padding: 3px 10px;"
                               " font-size: 11px; font-weight: 700;")
            cantidad = len(grupo['vins'])
            if estado in ('ok', 'nuevo'):
                cuentas['ok'] += cantidad
                a_crear += cantidad
            elif estado == 'varias':
                cuentas['varias'] += cantidad
            else:
                cuentas['sin'] += cantidad
                sin_coincidencia += cantidad
                if estado == 'sin_cliente':
                    a_crear += cantidad
        for clave, numero in self._cuentas.items():
            numero.setText(str(cuentas[clave]))
        sin_total = cuentas['sin']
        self.aviso.setVisible(sin_total > 0 and not self.nuevo_contrato)
        self.lbl_aviso.setText(f"{sin_total} {'camión no está' if sin_total == 1 else 'camiones no están'} en Comercial")
        fuera = sum(len(g['vins']) for g in self._grupos) - a_crear
        self.lbl_pie.setText(f"Se crean {_plural_camiones(a_crear)}." + (f" {fuera} se quedan para después." if fuera else ""))
        self.btn_confirmar.setText(f"Crear {a_crear} en el Registro Maestro" if a_crear else "Crear en el Registro Maestro")
        self.btn_confirmar.setEnabled(a_crear > 0 and self._hilo is None)

    # -------------------------------------------------------- acciones
    def _importar_power_bi(self):
        from src.ui.compartido import saltos
        self.reject()
        saltos.abrir_importacion_power_bi()

    def _registros_a_crear(self):
        registros, grupos = [], []
        for grupo in self._grupos:
            estado = self._estado_grupo(grupo)
            if estado not in ('ok', 'nuevo', 'sin_cliente'):
                continue
            candidato = grupo['candidatos'][grupo['indice']] if grupo['indice'] is not None else None
            for vin, cambios in grupo['vins']:
                cambios = cambios or {}
                registros.append(_construir_registro_nuevo_desde_provisiones(
                    vin, cambios.get('TIPO DE SERVICIO', ''), cambios.get('DURACIÓN (MESES)', ''),
                    candidato=candidato, forma_contrato=self._forma_contrato()))
            grupos.append(grupo)
        return registros, grupos

    def _confirmar(self):
        registros, grupos = self._registros_a_crear()
        if not registros:
            return
        self.btn_confirmar.setEnabled(False)
        self._hilo = _CrearLoteThread(ExcelWriter(), registros, "Provisiones (Vinculación RM)")
        self._hilo.finished_signal.connect(lambda ok: self._on_creado(ok, registros, grupos))
        self._hilo.start()

    def _on_creado(self, exito, registros, grupos):
        self._hilo = None
        if not exito:
            self._refrescar_estado()
            QMessageBox.warning(self, "Error", "No se pudieron crear los registros en la Base Comercial.")
            return
        dm = self.data_manager
        if self.nuevo_contrato:
            dm.load_data_async()
        elif not dm.df_master.empty:
            for registro in registros:
                dm.df_master = comercial_services.agregar_fila(dm.df_master, registro)
            dm.data_ready.emit()
        for registro in registros:
            self.vin_resuelto.emit(registro['VIN'])
        QMessageBox.information(self, "Vinculado", f"Se crearon {_plural_camiones(len(registros))} en la Base Comercial.")
        creados = {id(g) for g in grupos}
        self._grupos = [g for g in self._grupos if id(g) not in creados]
        if not self._grupos:
            self.accept()
            return
        self._llenar_tabla()
        self._refrescar_estado()


class _CrearLoteThread(QThread):
    """Escribe todos los registros nuevos con una sola apertura y un solo respaldo."""
    finished_signal = pyqtSignal(bool)

    def __init__(self, writer, lote, module_name):
        super().__init__()
        self.writer = writer
        self.lote = lote
        self.module_name = module_name

    def run(self):
        self.finished_signal.emit(bool(self.writer.add_new_rows_batch(self.lote, module_name=self.module_name)))


class VinsHuerfanosAlertDialog(QDialog):
    """Aviso de camiones nuevos en Provisiones sin ficha en el Registro Maestro. Recomienda importar primero
    desde Power BI y vincular solo lo que quede. `eleccion` queda en 'importar', 'vincular' o None (más tarde)."""

    def __init__(self, vins_huerfanos, parent=None):
        super().__init__(parent)
        self.eleccion = None
        self.setWindowTitle("Camiones nuevos en Provisiones")
        self.setMinimumWidth(740)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        encabezado = QHBoxLayout()
        encabezado.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(46, 46)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setStyleSheet("background: #E6EFFD; border-radius: 12px;")
        icono.setPixmap(ThemeManager.icon('fa5s.truck-loading', color=PRIMARY).pixmap(QSize(24, 24)))
        encabezado.addWidget(icono)
        columna = QVBoxLayout()
        columna.setSpacing(2)
        total = len(vins_huerfanos)
        columna.addWidget(_etiqueta(f"{_plural_camiones(total)} sin ficha en el Registro Maestro",
                                    "color: #0F1B33; font-size: 18px; font-weight: 800;"))
        columna.addWidget(_etiqueta("Provisiones ya los tiene, pero Comercial todavía no sabe a qué cliente pertenecen.",
                                    "color: #5B6B86; font-size: 12px;"))
        encabezado.addLayout(columna, 1)
        layout.addLayout(encabezado)

        pasos = QHBoxLayout()
        pasos.setSpacing(12)
        pasos.addWidget(self._tarjeta_paso(
            "1", "Primero", "Importar desde Power BI",
            "El reporte de Notas de Venta trae cliente, RUT, CDB y ejecutivo de cada unidad. Es la forma más "
            "completa de crear las fichas.", recomendado=True))
        pasos.addWidget(self._tarjeta_paso(
            "2", "Después", "Vincular los que queden",
            "Con lo que no venga en Power BI, enlaza los camiones a clientes que ya existan en Comercial.", recomendado=False))
        layout.addLayout(pasos)

        clientes = _clientes_por_vin(getattr(parent, 'data_manager', None)) if parent is not None else {}
        tabla = QTableWidget(len(vins_huerfanos), 2)
        tabla.setHorizontalHeaderLabels(["VIN", "CLIENTE EN PROVISIONES"])
        tabla.setStyleSheet(_QSS_TABLA_VINCULO)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setShowGrid(False)
        tabla.verticalHeader().setVisible(False)
        tabla.verticalHeader().setDefaultSectionSize(32)
        tabla.horizontalHeader().setStretchLastSection(True)
        tabla.setColumnWidth(0, 200)
        for fila, (vin, _cambios) in enumerate(vins_huerfanos):
            tabla.setItem(fila, 0, QTableWidgetItem(str(vin)))
            nombre = QTableWidgetItem(clientes.get(str(vin).strip().upper(), '-') or '-')
            fuente = nombre.font()
            fuente.setBold(True)
            nombre.setFont(fuente)
            tabla.setItem(fila, 1, nombre)
        tabla.setFixedHeight(min(180, 40 + 32 * max(1, total)))
        marco = QFrame()
        marco.setObjectName("marcoListaHuerfanos")
        marco.setStyleSheet("QFrame#marcoListaHuerfanos { background: white; border: 1px solid #DDE3EE; border-radius: 12px; }")
        lay_marco = QVBoxLayout(marco)
        lay_marco.setContentsMargins(1, 1, 1, 1)
        lay_marco.addWidget(tabla)
        layout.addWidget(marco)
        layout.addWidget(_etiqueta("Si eliges Más tarde, este aviso vuelve a salir al guardar.",
                                   "color: #5B6B86; font-size: 12px;"))

        botones = QHBoxLayout()
        botones.setSpacing(10)
        botones.addStretch(1)
        self.btn_despues = QPushButton("Más tarde")
        ThemeManager.apply_secondary_button(self.btn_despues)
        self.btn_despues.clicked.connect(self.reject)
        botones.addWidget(self.btn_despues)

        self.btn_vincular = QPushButton("Vincular ahora")
        self.btn_vincular.setStyleSheet(_QSS_BOTON_CONTORNO)
        self.btn_vincular.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vincular.clicked.connect(lambda: self._elegir('vincular'))
        botones.addWidget(self.btn_vincular)

        self.btn_importar = QPushButton("Importar desde Power BI")
        self.btn_importar.setStyleSheet(_QSS_BOTON_NAVY)
        self.btn_importar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_importar.clicked.connect(lambda: self._elegir('importar'))
        botones.addWidget(self.btn_importar)
        layout.addLayout(botones)
        self.adjustSize()

    @staticmethod
    def _tarjeta_paso(numero, momento, titulo, texto, recomendado):
        tarjeta = QFrame()
        tarjeta.setObjectName("pasoHuerfanos")
        borde, fondo = ("#2563EB", "#E6EFFD") if recomendado else ("#DDE3EE", "#F6F8FC")
        tarjeta.setStyleSheet(f"QFrame#pasoHuerfanos {{ background: {fondo}; border: 1px solid {borde}; border-radius: 12px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(5)
        if recomendado:
            etiqueta = QLabel("RECOMENDADO")
            etiqueta.setStyleSheet("background: #003057; color: white; border-radius: 9px; padding: 2px 9px;"
                                   " font-size: 10px; font-weight: 800;")
            lay.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignLeft)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        circulo = QLabel(numero)
        circulo.setFixedSize(22, 22)
        circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        circulo.setStyleSheet("background: #003057; color: white; border-radius: 11px; font-size: 11px; font-weight: 700;")
        fila.addWidget(circulo)
        fila.addWidget(_etiqueta(momento, "color: #5B6B86; font-size: 12px; font-weight: 700;", False))
        fila.addStretch(1)
        lay.addLayout(fila)
        lay.addWidget(_etiqueta(titulo, "color: #0F1B33; font-size: 14px; font-weight: 800;"))
        lay.addWidget(_etiqueta(texto, "color: #5B6B86; font-size: 12px;"))
        return tarjeta

    def _elegir(self, eleccion):
        self.eleccion = eleccion
        self.accept()


class ProvisionFormDialog(QDialog):
    """Formulario de un registro de Provision (VIN + período). El período
    (AÑO - MES) nunca se edita -- igual que en la tabla actual, donde no es
    una columna editable -- por eso aquí es de solo lectura. DYNAFLEET,
    Cantidad de Meses y Plan sí se editan, y Monto Provisionado/Valor
    Plan/VAR se recalculan en vivo con la misma formula que ya usa
    ProvisionesModule.on_item_edited (provisiones_services.calcular_montos_provision),
    para que el usuario vea el resultado antes de guardar. Guardar reenvia
    los campos editados a on_item_edited (una llamada por columna) y termina
    en confirm_save(), igual que ContratoFormDialog en contratos.py."""

    guardado = pyqtSignal(str, str, dict)

    def __init__(self, cliente, fila, planes_data, uf, parent=None, industria="-"):
        super().__init__(parent)
        self.fila = dict(fila)
        self.planes_data = planes_data
        self.uf = uf
        self.setWindowTitle("Editar Provisión")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("form_card_prov")
        card.setStyleSheet(f"QFrame#form_card_prov {{ background-color: {SURFACE}; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("background-color: #F5F3FF;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon('fa5s.truck', color=MODULE_ACCENT_PROV).pixmap(16, 16))
        header_layout.addWidget(icon_lbl)
        header_layout.addSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        titulo = QLabel(f"Provisión {self.fila.get('VIN', '-')}")
        titulo.setStyleSheet(f"font-size: 13px; color: {MODULE_ACCENT_PROV}; font-weight: bold; background: transparent;")
        subtitulo = QLabel(f"{cliente}  ·  {self.fila.get('AÑO - MES', '-')}")
        subtitulo.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY}; background: transparent;")
        text_col.addWidget(titulo)
        text_col.addWidget(subtitulo)
        header_layout.addLayout(text_col)
        header_layout.addStretch()
        card_layout.addWidget(header)

        fields_frame = QFrame()
        fields_layout = QVBoxLayout(fields_frame)
        fields_layout.setContentsMargins(16, 14, 16, 16)
        fields_layout.setSpacing(10)

        def _campo(etiqueta, valor, solo_lectura):
            box = QVBoxLayout()
            box.setSpacing(2)
            lbl = QLabel(etiqueta)
            lbl.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold;")
            campo = QLineEdit(str(valor) if valor not in (None, "") else "-")
            campo.setReadOnly(solo_lectura)
            box.addWidget(lbl)
            box.addWidget(campo)
            return box, campo

        row1 = QHBoxLayout(); row1.setSpacing(10)
        box, _ = _campo("VIN", self.fila.get('VIN', '-'), True)
        row1.addLayout(box, 1)
        box, _ = _campo("PERÍODO (AÑO - MES)", self.fila.get('AÑO - MES', '-'), True)
        row1.addLayout(box, 1)
        fields_layout.addLayout(row1)

        row_info = QHBoxLayout(); row_info.setSpacing(10)
        box, _ = _campo("INDUSTRIA", industria, True)
        row_info.addLayout(box, 1)
        box, _ = _campo("OBSERVACIONES", self.fila.get('OBSERVACIONES', '-'), True)
        row_info.addLayout(box, 1)
        fields_layout.addLayout(row_info)

        row2 = QHBoxLayout(); row2.setSpacing(10)
        box, self.input_dynafleet = _campo("DYNAFLEET (COBRO)", self.fila.get('DYNAFLEET', '$-'), False)
        row2.addLayout(box, 1)
        box, self.input_meses = _campo("CANTIDAD DE MESES", self.fila.get('Cantidad de Meses', '-'), False)
        row2.addLayout(box, 1)
        fields_layout.addLayout(row2)

        row3 = QHBoxLayout(); row3.setSpacing(10)
        box_plan = QVBoxLayout(); box_plan.setSpacing(2)
        lbl_plan = QLabel("PLAN")
        lbl_plan.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold;")
        self.combo_plan = estilo_com.ComboTarjeta("Plan")
        self.combo_plan.addItems(_PLAN_OPCIONES)
        ThemeManager.apply_combo_box(self.combo_plan)
        self.combo_plan.setMaxVisibleItems(8)
        valor_plan = str(self.fila.get('Plan', '-')).strip()
        idx_plan = next((i for i, p in enumerate(_PLAN_OPCIONES) if p.upper() == valor_plan.upper()), -1)
        if idx_plan >= 0:
            self.combo_plan.setCurrentIndex(idx_plan)
        box_plan.addWidget(lbl_plan)
        box_plan.addWidget(self.combo_plan)
        row3.addLayout(box_plan, 1)
        fields_layout.addLayout(row3)

        calc_frame = QFrame()
        calc_frame.setStyleSheet(f"background-color: {BACKGROUND}; border-radius: 8px;")
        calc_layout = QHBoxLayout(calc_frame)
        calc_layout.setContentsMargins(12, 10, 12, 10)
        calc_layout.setSpacing(10)

        def _campo_calculado(etiqueta):
            box = QVBoxLayout(); box.setSpacing(2)
            lbl = QLabel(etiqueta)
            lbl.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold; background: transparent;")
            valor = QLabel("$-")
            valor.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {MODULE_ACCENT_PROV}; background: transparent;")
            box.addWidget(lbl)
            box.addWidget(valor)
            calc_layout.addLayout(box, 1)
            return valor

        self.lbl_monto_calc = _campo_calculado("MONTO PROVISIONADO")
        self.lbl_valor_plan_calc = _campo_calculado("VALOR PLAN")
        self.lbl_var_calc = _campo_calculado("VAR")
        fields_layout.addWidget(calc_frame)

        card_layout.addWidget(fields_frame)
        layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 0, 16, 16)
        btn_row.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        ThemeManager.apply_secondary_button(btn_cancelar)
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton(" Guardar")
        btn_guardar.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_primary_button(btn_guardar)
        btn_guardar.clicked.connect(self._on_guardar)
        btn_row.addWidget(btn_cancelar)
        btn_row.addWidget(btn_guardar)
        layout.addLayout(btn_row)

        self.input_dynafleet.textChanged.connect(self._formatear_dynafleet_en_vivo)
        self.input_meses.textChanged.connect(self._formatear_meses_en_vivo)
        self.combo_plan.currentTextChanged.connect(self._recalcular)
        self._recalcular()

    def _formatear_dynafleet_en_vivo(self, texto):
        """Solo permite digitos o '-' (a pedido del usuario, 20-09-2026):
        cualquier otro caracter se descarta al vuelo, y los digitos se
        reformatean de inmediato como '$XXX.XXX.XXX' mientras se escribe. Un
        '-' inicial se conserva como signo negativo (DYNAFLEET si admite
        valores negativos, ver provisiones_services.parsear_dynafleet);
        un '-' solo (sin digitos) queda tal cual mientras se sigue
        escribiendo."""
        negativo = texto.strip().startswith('-')
        solo_digitos = ''.join(c for c in texto if c.isdigit())
        if not solo_digitos:
            nuevo = '-' if negativo else ''
        else:
            signo = '-' if negativo else ''
            nuevo = f"{signo}${int(solo_digitos):,}".replace(',', '.')
        if nuevo != texto:
            self.input_dynafleet.blockSignals(True)
            self.input_dynafleet.setText(nuevo)
            self.input_dynafleet.setCursorPosition(len(nuevo))
            self.input_dynafleet.blockSignals(False)
        self._recalcular()

    def _formatear_meses_en_vivo(self, texto):
        """Mismo criterio que DYNAFLEET (solo digitos o '-'), pero sin
        formato de miles -- Cantidad de Meses es un numero simple."""
        if texto.strip() == '-':
            nuevo = '-'
        else:
            nuevo = ''.join(c for c in texto if c.isdigit())
        if nuevo != texto:
            self.input_meses.blockSignals(True)
            self.input_meses.setText(nuevo)
            self.input_meses.setCursorPosition(len(nuevo))
            self.input_meses.blockSignals(False)
        self._recalcular()

    def _valores_actuales(self):
        """Mismo parseo que on_item_edited, pero solo para el recalculo en
        vivo del dialogo (no valida ni muestra errores -- eso lo hace
        on_item_edited al guardar de verdad)."""
        _, dato = provisiones_services.parsear_dynafleet(self.input_dynafleet.text())
        val_dynafleet = dato["num"] if dato else 0.0

        val_meses = 1.0
        meses_txt = str(self.input_meses.text()).strip()
        if meses_txt and meses_txt.upper() not in ("-", "MENSUAL"):
            try:
                val_meses = float(meses_txt)
            except ValueError:
                val_meses = 1.0

        return val_dynafleet, val_meses, self.combo_plan.currentText().strip()

    def _recalcular(self):
        val_dynafleet, val_meses, nombre_plan = self._valores_actuales()
        monto_prov, valor_plan_exacto, variacion = provisiones_services.calcular_montos_provision(
            val_dynafleet, val_meses, nombre_plan, self.planes_data, self.uf
        )
        self.lbl_monto_calc.setText(_formato_moneda_prov(monto_prov))
        self.lbl_valor_plan_calc.setText(_formato_moneda_prov(valor_plan_exacto))
        self.lbl_var_calc.setText(_formato_moneda_prov(variacion))

        # Mismo criterio de color que tenia la tabla original
        # (ProvisionesTableModel): rojo si VAR es negativo, verde si es
        # positivo, color neutro si es exactamente cero.
        if variacion < 0:
            color_var = DANGER
        elif variacion > 0:
            color_var = SUCCESS
        else:
            color_var = TEXT_SECONDARY
        self.lbl_var_calc.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color_var}; background: transparent;")

    def _on_guardar(self):
        cambios = {
            'DYNAFLEET': self.input_dynafleet.text(),
            'Cantidad de Meses': self.input_meses.text(),
            'Plan': self.combo_plan.currentText(),
        }
        vin = str(self.fila.get('VIN', '')).strip()
        periodo = str(self.fila.get('AÑO - MES', '')).strip()
        self.guardado.emit(vin, periodo, cambios)
        self.accept()
