"""Diálogos de Contratos (CM): pasar a CM, extender duración, VIN nuevos y vincular con Comercial."""
from src.theme.colors import BACKGROUND, BORDER, PRIMARY, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY
import pandas as pd
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QDialog, QListWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem, QSpinBox
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from src.core.excel_writer import ExcelWriter
from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.theme_manager import ThemeManager
from src.services import comercial_services
from src.services import contratos_service as ct_service
from src.services import provisiones_services
from src.core.constants import COL_ESTADO_COMERCIAL


class ResumenPasarACM(QDialog):
    """Resumen previo a "Pasar a CM": un grupo por cambio (forma y facturación antes → ahora) que se
    abre para ver cada VIN con su contrato y su facturación antiguos y nuevos."""

    def __init__(self, parent, filas):
        super().__init__(parent)
        self.setWindowTitle("Pasar a CM")
        self.setModal(True)
        self.resize(780, 640)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 20, 20, 20)
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaResumenCm")
        tarjeta.setStyleSheet(f"QFrame#tarjetaResumenCm {{ background-color: {SURFACE}; border-radius: 14px; border: 1px solid {BORDER}; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        titulo = QLabel("Pasar a CM")
        titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 800; background: transparent; border: none;")
        sub = QLabel(f"{len(filas)} contrato(s) cambian de forma y facturación")
        sub.setStyleSheet("color: #1D4ED8; font-size: 13px; font-weight: 700; background: transparent; border: none;")
        ayuda = QLabel("La forma pasa a CMG, CMB o CMS según el tipo de CM del 3PC y la facturación a CM. "
                       "Abre un grupo para ver cada VIN.")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12.5px; background: transparent; border: none;")
        for w in (titulo, sub, ayuda):
            lay.addWidget(w)
        nuevos = sum(1 for f in filas if f.get('contrato_nuevo'))
        if nuevos:
            aviso = QLabel(f"{nuevos} Provisión(es) crean un contrato CM nuevo: la Provisión queda como Renovado en el "
                           "historial y los datos del 3PC pasan al contrato nuevo (duración \"-\", término MENSUAL).")
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color: #1D4ED8; font-size: 12.5px; background: transparent; border: none;")
            lay.addWidget(aviso)

        arbol = QTreeWidget()
        arbol.setColumnCount(3)
        arbol.setHeaderLabels(["VIN", "Contrato (antes → ahora)", "Facturación (antes → ahora)"])
        arbol.setRootIsDecorated(True)
        arbol.setUniformRowHeights(True)
        arbol.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        arbol.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        arbol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        arbol.setStyleSheet(
            f"QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; font-size: 12.5px; }}"
            "QTreeWidget::item { padding: 6px 4px; }"
            f"QHeaderView::section {{ background: #F7F8FC; color: {TEXT_SECONDARY}; border: none; padding: 8px; font-size: 11px; font-weight: 700; }}")
        grupos = {}
        for f in filas:
            clave = (f['forma_antes'], f['fact_antes'], f['forma_ahora'], f['fact_ahora'])
            grupos.setdefault(clave, []).append(f)
        negrita = arbol.font()
        negrita.setBold(True)
        for (forma_a, fact_a, forma_n, fact_n), items in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
            cabecera = QTreeWidgetItem([f"{forma_a} / {fact_a}  →  {forma_n} / {fact_n}   ·   {len(items)} contrato(s)"])
            cabecera.setFont(0, negrita)
            arbol.addTopLevelItem(cabecera)
            cabecera.setFirstColumnSpanned(True)
            for f in items:
                sufijo = "  (contrato nuevo)" if f.get('contrato_nuevo') else ""
                cabecera.addChild(QTreeWidgetItem([f['vin'], f"{f['forma_antes']}  →  {f['forma_ahora']}{sufijo}",
                                                   f"{f['fact_antes']}  →  {f['fact_ahora']}"]))
        arbol.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        arbol.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        arbol.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        if arbol.topLevelItemCount():
            arbol.topLevelItem(0).setExpanded(True)
        lay.addWidget(arbol, 1)

        nota = QLabel("La etapa de gestión se recalcula sola.")
        nota.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;")
        pie = QHBoxLayout()
        pie.addWidget(nota, 1)
        cancelar = QPushButton("Cancelar")
        aceptar = QPushButton(f"Aplicar a los {len(filas)}")
        ThemeManager.apply_secondary_button(cancelar)
        ThemeManager.apply_primary_button(aceptar)
        cancelar.clicked.connect(self.reject)
        aceptar.clicked.connect(self.accept)
        pie.addWidget(cancelar)
        pie.addWidget(aceptar)
        lay.addLayout(pie)
        raiz.addWidget(tarjeta)


class ExtenderDuracionDialog(QDialog):
    """Meses a sumar a los contratos seleccionados, con el término antes y después de cada uno."""

    def __init__(self, parent, filas):
        super().__init__(parent)
        self._filas = filas
        self.setWindowTitle("Extender duración")
        self.setModal(True)
        self.resize(560, 560)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 20, 20, 20)
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaExtender")
        tarjeta.setStyleSheet(f"QFrame#tarjetaExtender {{ background-color: {SURFACE}; border-radius: 14px; border: 1px solid {BORDER}; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        titulo = QLabel("Extender duración")
        titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 800; background: transparent; border: none;")
        sub = QLabel(f"{len(filas)} contrato(s). El contrato conserva su ID y su término se recalcula desde el inicio.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12.5px; background: transparent; border: none;")
        lay.addWidget(titulo)
        lay.addWidget(sub)

        fila_meses = QHBoxLayout()
        self._spin = QSpinBox()
        self._spin.setRange(1, 120)
        self._spin.setValue(12)
        self._spin.setSuffix(" meses")
        self._spin.setFixedHeight(38)
        self._spin.valueChanged.connect(self._actualizar_lista)
        fila_meses.addWidget(self._spin, 1)
        for meses in (6, 12, 24, 36):
            chip = QPushButton(str(meses))
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            ThemeManager.apply_secondary_button(chip)
            chip.clicked.connect(lambda _c=False, m=meses: self._spin.setValue(m))
            fila_meses.addWidget(chip)
        lay.addLayout(fila_meses)

        self._lista = QListWidget()
        self._lista.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._lista.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._lista.setStyleSheet(f"QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; font-size: 12px; }}"
                                  "QListWidget::item { padding: 6px 8px; }")
        lay.addWidget(self._lista, 1)

        pie = QHBoxLayout()
        pie.addStretch(1)
        cancelar = QPushButton("Cancelar")
        aceptar = QPushButton("Extender duración")
        ThemeManager.apply_secondary_button(cancelar)
        ThemeManager.apply_primary_button(aceptar)
        cancelar.clicked.connect(self.reject)
        aceptar.clicked.connect(self.accept)
        pie.addWidget(cancelar)
        pie.addWidget(aceptar)
        lay.addLayout(pie)
        raiz.addWidget(tarjeta)
        self._actualizar_lista()

    def meses(self):
        return self._spin.value()

    def _actualizar_lista(self, *_args):
        self._lista.clear()
        for vin, fila in self._filas.items():
            cambios = comercial_services.calcular_renovacion(fila, self._spin.value()) or {}
            termino = pd.to_datetime(fila.get('TÉRMINO CONTRATO'), errors='coerce')
            antes = termino.strftime("%d-%m-%Y") if pd.notna(termino) else str(fila.get('TÉRMINO CONTRATO', '-')).strip() or '-'
            estado = str(fila.get(COL_ESTADO_COMERCIAL, '')).strip().capitalize()
            nuevo_estado = str(cambios.get(COL_ESTADO_COMERCIAL, estado)).capitalize()
            self._lista.addItem(f"{vin}   ·   término {antes} → {cambios.get('TÉRMINO CONTRATO', '-')}   ·   {estado} → {nuevo_estado}")


# =========================================================
# VIN NUEVOS SIN FICHA EN COMERCIAL (mismo camino que Provisiones)
# =========================================================
class VinsNuevosContratoAlertDialog(QDialog):
    """Alerta simple (30-09-2026) para los VIN que trae el Excel de
    Contratos CM (3PC) pero que todavia no tienen fila en Comercial (RM):
    hoy importar_excel_javiera() los ignora en silencio porque solo
    actualiza VIN que ya existen. Mismo patron visual y misma idea que
    provisiones.py::VinsHuerfanosAlertDialog -- unico camino para
    resolverlos es abrir VincularContratoComercialDialog."""

    def __init__(self, vins_nuevos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contratos nuevos sin ficha en Comercial")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        encabezado = QHBoxLayout()
        encabezado.setSpacing(12)
        icono = QLabel()
        icono.setPixmap(ThemeManager.icon('fa5s.truck-loading', color=PRIMARY).pixmap(QSize(30, 30)))
        encabezado.addWidget(icono)
        titulo = QLabel(f"{len(vins_nuevos)} contrato(s) sin ficha en Comercial")
        titulo.setWordWrap(True)
        ThemeManager.style_subtitle(titulo)
        encabezado.addWidget(titulo, stretch=1)
        layout.addLayout(encabezado)

        explicacion = QLabel(
            "El Excel de Contratos CM trae datos para estos VIN, pero todavía no existen en la "
            "Base Comercial (PruebasFM) -- hoy quedan ignorados. Podés vincularlos ahora con un "
            "cliente que ya exista en Comercial (Razón Social, RUT, CDB) usando el nombre que trae "
            "el propio Excel, o hacerlo más tarde."
        )
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(explicacion)

        lista = QListWidget()
        lista.addItems([f"{info['VIN']} · {info.get('CLIENTE', '-')}" for info in vins_nuevos])
        lista.setMaximumHeight(130)
        layout.addWidget(lista)

        botones = QHBoxLayout()
        botones.addStretch()
        self.btn_despues = QPushButton(" Más tarde")
        ThemeManager.apply_secondary_button(self.btn_despues)
        self.btn_despues.clicked.connect(self.reject)
        botones.addWidget(self.btn_despues)

        self.btn_vincular = QPushButton(" Vincular ahora")
        self.btn_vincular.setIcon(ThemeManager.icon('fa5s.link', color='white'))
        ThemeManager.apply_primary_button(self.btn_vincular)
        self.btn_vincular.clicked.connect(self.accept)
        botones.addWidget(self.btn_vincular)
        layout.addLayout(botones)


class VincularContratoComercialDialog(QDialog):
    """Único camino para resolver un VIN de Contratos CM sin ficha en
    Comercial. A diferencia de provisiones.py::VincularComercialDialog (que
    saca el 'CLIENTE' de Provisiones), acá el nombre del cliente viene
    directo del propio Excel de Javiera (columna "Current Invoicing
    Customer Name"), así que no hace falta cruzar con otro archivo. Busca
    candidatos contra la Razón Social ya existente en Comercial con
    provisiones_services.buscar_candidatos_por_cliente() (función pura,
    sin nada específico de Provisiones) y arma el registro nuevo con
    contratos_service.construir_registro_nuevo_desde_contrato_cm(), que
    reutiliza los mismos defaults de 'Gestión de Unidades'."""

    vin_resuelto = pyqtSignal(str)

    def __init__(self, vins_pendientes, data_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vincular con Comercial (RM)")
        self.resize(760, 560)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        self.data_manager = data_manager
        self.vins_pendientes = list(vins_pendientes)
        self.candidatos_actuales = []
        self._add_thread = None
        self._setup_ui()
        self._cargar_vin_actual()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("VIN a vincular:"))
        self.combo_vin = estilo_com.ComboTarjeta("VIN a vincular")
        self.combo_vin.addItems([info['VIN'] for info in self.vins_pendientes])
        self.combo_vin.currentIndexChanged.connect(self._cargar_vin_actual)
        layout.addWidget(self.combo_vin)

        self.lbl_cliente = QLabel()
        self.lbl_cliente.setWordWrap(True)
        self.lbl_cliente.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.lbl_cliente)

        layout.addWidget(QLabel("Coincidencias encontradas en Comercial (selecciona una; ninguna si no corresponde):"))
        self.tabla_candidatos = QTableWidget(0, 4)
        self.tabla_candidatos.setHorizontalHeaderLabels(["Razón Social", "RUT", "CDB", "Ejecutivo"])
        self.tabla_candidatos.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla_candidatos.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla_candidatos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_candidatos.horizontalHeader().setStretchLastSection(True)
        self.tabla_candidatos.itemSelectionChanged.connect(self._actualizar_preview)
        layout.addWidget(self.tabla_candidatos, stretch=1)

        self.lbl_preview = QLabel()
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 11px; padding: 8px; background-color: white; border-radius: 6px;"
        )
        layout.addWidget(self.lbl_preview)

        btn_layout = QHBoxLayout()
        self.btn_cerrar = QPushButton(" Cerrar")
        ThemeManager.apply_secondary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.close)

        self.btn_confirmar = QPushButton(" Confirmar y Crear en RM")
        ThemeManager.apply_primary_button(self.btn_confirmar)
        self.btn_confirmar.clicked.connect(self._confirmar)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cerrar)
        btn_layout.addWidget(self.btn_confirmar)
        layout.addLayout(btn_layout)

    def _vin_actual(self):
        idx = self.combo_vin.currentIndex()
        if idx < 0 or idx >= len(self.vins_pendientes):
            return None
        return self.vins_pendientes[idx]

    def _cargar_vin_actual(self):
        self.tabla_candidatos.setRowCount(0)
        self.candidatos_actuales = []
        self.lbl_preview.clear()

        info = self._vin_actual()
        if not info:
            self.lbl_cliente.setText("")
            self.btn_confirmar.setEnabled(False)
            return

        cliente = info.get('CLIENTE', '')
        self.lbl_cliente.setText(f'Cliente en el Excel de Contratos: "{cliente}"')
        self.candidatos_actuales = provisiones_services.buscar_candidatos_por_cliente(
            self.data_manager.df_master, cliente
        )

        self.tabla_candidatos.setRowCount(len(self.candidatos_actuales))
        for row, cand in enumerate(self.candidatos_actuales):
            for col, campo in enumerate(['RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO']):
                self.tabla_candidatos.setItem(row, col, QTableWidgetItem(str(cand.get(campo, ''))))

        self.btn_confirmar.setEnabled(True)
        self._actualizar_preview()

    def _candidato_seleccionado(self):
        filas = self.tabla_candidatos.selectionModel().selectedRows() if self.tabla_candidatos.selectionModel() else []
        if not filas:
            return None
        return self.candidatos_actuales[filas[0].row()]

    def _actualizar_preview(self):
        info = self._vin_actual()
        if not info:
            return
        registro = ct_service.construir_registro_nuevo_desde_contrato_cm(info['VIN'], info, self._candidato_seleccionado())
        self.lbl_preview.setText(
            f"VIN: {registro['VIN']}  ·  CHASIS: {registro['CHASIS']}  ·  MODELO: {registro['MODELO']}\n"
            f"Razón Social: {registro['RAZÓN SOCIAL'] or '(sin coincidencia)'}  ·  "
            f"RUT: {registro['RUT'] or '-'}  ·  CDB: {registro['CDB'] or '-'}  ·  "
            f"Ejecutivo: {registro['EJECUTIVO'] or '-'}\n"
            f"N° Contrato 3PC: {registro['N CONTRATO 3PC']}  ·  "
            f"Tipo de CM: {registro['TIPO DE CM']}  ·  Estado del CM: {registro['ESTADO DEL CM']}\n"
            f"Fecha Inicio CM: {registro['FECHA INICIO CM']}  ·  Fecha Término CM: {registro['FECHA TERMINO CM']}  ·  "
            f"Pago CM: {registro['PAGO CM']}\n"
            f"Estado Comercial: {registro['ESTADO COMERCIAL']}  ·  "
            f"Forma de Contrato: {registro['FORMA DE CONTRATO']}  ·  "
            f"Etapa Gestión: {registro['ETAPA GESTIÓN']}\n"
            f"Observaciones: {registro['OBSERVACIONES']}"
        )

    def _confirmar(self):
        info = self._vin_actual()
        if not info:
            return
        candidato = self._candidato_seleccionado()
        if candidato is None:
            respuesta = QMessageBox.question(
                self, "Sin coincidencia comercial",
                f"No seleccionaste ninguna coincidencia para el VIN {info['VIN']}. Se creará igual, pero sin "
                "Razón Social/RUT/CDB/Ejecutivo (quedará marcado para revisión manual).\n\n¿Continuar?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

        registro = ct_service.construir_registro_nuevo_desde_contrato_cm(info['VIN'], info, candidato)
        id_nuevo = comercial_services.proximo_id_contrato(self.data_manager.df_master)
        if id_nuevo:
            registro['ID'] = id_nuevo

        from src.ui.comercial import AddRowThread
        self.btn_confirmar.setEnabled(False)
        self._add_thread = AddRowThread(ExcelWriter(), registro, module_name="Contratos CM (Vinculación RM)")
        self._add_thread.finished_signal.connect(lambda ok, data: self._on_creado(ok, data, info['VIN']))
        self._add_thread.start()

    def _on_creado(self, success, new_data, vin):
        self.btn_confirmar.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "Error", f"No se pudo crear el registro para VIN {vin} en la Base Comercial.")
            return

        dm = self.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            dm.data_ready.emit()

        QMessageBox.information(self, "Vinculado", f"Se creó el registro para VIN {vin} en la Base Comercial.")
        self.vins_pendientes = [info for info in self.vins_pendientes if info['VIN'] != vin]
        self.vin_resuelto.emit(vin)

        self.combo_vin.blockSignals(True)
        self.combo_vin.clear()
        self.combo_vin.addItems([info['VIN'] for info in self.vins_pendientes])
        self.combo_vin.blockSignals(False)

        if not self.vins_pendientes:
            QMessageBox.information(self, "Listo", "No quedan VIN pendientes por vincular.")
            self.accept()
            return
        self._cargar_vin_actual()
