"""Hilo de la UF y diálogo de costos de Provisiones."""
import os
import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QLineEdit,
                             QDialog, QGridLayout, QTabWidget, QScrollArea, QStackedWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.services import catalogos_service, provisiones_services
import config.settings
from src.theme.theme_manager import ThemeManager
from src.ui.compartido.combo_multiple import ComboMultiple
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH


class FetchUfWorker(QThread):
    uf_fetched = pyqtSignal(float)
    error_signal = pyqtSignal(str)

    def run(self):
        try:
            import requests, re, urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            url = os.environ.get("GESTOR_SSCC_UF_URL", "").strip()
            if not url:
                self.error_signal.emit("Sin URL de UF: define la variable de entorno GESTOR_SSCC_UF_URL o ingresa el valor a mano.")
                return
            response = requests.get(url, timeout=10, verify=False)
            if response.status_code == 200:
                text_response = response.text.replace(',', '.')
                matches = re.findall(r'\b\d{5}(?:\.\d{1,2})?\b', text_response)
                if matches:
                    self.uf_fetched.emit(float(matches[0]))
                    return
            self.error_signal.emit("No se pudo extraer la UF.")
        except Exception as e:
            self.error_signal.emit(str(e))


def _texto_numero(valor):
    """Número sin ceros de más ni notación científica (0.28, 38000.55)."""
    return f"{float(valor):.4f}".rstrip('0').rstrip('.') or "0"


def _clp(valor):
    return "$" + f"{valor:,.0f}".replace(",", ".")


class CostosDialog(QDialog):
    """Dos pestañas: Valores (consulta compacta) y Modificar (UF, complementos y multiplicador de cada plan).
    Los planes con complementos no se listan: su precio es el del plan base más los complementos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de Costos y UF")
        self.setStyleSheet("QDialog { background-color: #FFFFFF; }")
        self.data_manager = DataManager()
        self.uf_worker = None
        self._codigos = {c for c, _n in catalogos_service.complementos(solo_activos=False)}
        self._complementos = []
        self._planes = []
        self._filas_valores = []
        self._valores_hoja = {}
        self._override = {}
        self._setup_ui()
        self.load_current_data()

    _QSS_CAMPO = (
        "QLineEdit { background: #FFFFFF; color: #14213D; border: 1px solid #DCE3EC; border-radius: 10px; "
        "padding: 0 12px; min-height: 32px; font-size: 12px; font-weight: 600; }"
        "QLineEdit:focus { border: 1px solid #1B2B4E; }")
    _QSS_BTN_PRIM = (
        "QPushButton { background: #1B2B4E; color: white; border: none; border-radius: 10px; padding: 0 18px; "
        "min-height: 34px; font-weight: 700; font-size: 12px; } "
        "QPushButton:hover { background: #2C4A80; } QPushButton:disabled { background: #A9B3C4; }")
    _QSS_BTN_SEC = (
        "QPushButton { background: #FFFFFF; color: #14213D; border: 1px solid #E1E7F0; border-radius: 10px; "
        "padding: 0 18px; min-height: 34px; font-weight: 700; font-size: 12px; } "
        "QPushButton:hover { background: #F1F4F9; }")
    _QSS_TABS = (
        "QTabWidget::pane { border: none; border-top: 1px solid #E1E7F0; }"
        "QTabBar::tab { background: transparent; color: #6B7A93; padding: 8px 18px; font-weight: 700; font-size: 12px; "
        "border: none; border-bottom: 2px solid transparent; }"
        "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 2px solid #1B2B4E; }")
    _QSS_COMBO = (
        "QComboBox { background: #FFFFFF; color: #14213D; border: 1px solid #DCE3EC; border-radius: 10px; "
        "padding: 4px 10px; min-height: 24px; font-size: 12px; font-weight: 600; combobox-popup: 0; }"
        "QComboBox:hover { border: 1px solid #B9C6DA; }"
        "QComboBox:focus, QComboBox:on { border: 1px solid #1B2B4E; }"
        "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; "
        "border: none; border-left: 1px solid #E3E8F0; border-top-right-radius: 9px; border-bottom-right-radius: 9px; "
        f"background-color: #F7F8FC; }}QComboBox::down-arrow {{ image: url({_COMBO_CHEVRON_PATH}); width: 11px; height: 11px; }}")

    @staticmethod
    def _etiqueta(texto):
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #6B7A93; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        return lbl

    @staticmethod
    def _titulo(texto):
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #6B7A93; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                          "background: transparent; border: none;")
        return lbl

    @staticmethod
    def _encabezado_columna(texto, derecha=False):
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #6B7A93; font-size: 10px; font-weight: 800; letter-spacing: 0.8px; "
                          "background: transparent; border: none;")
        if derecha:
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        return lbl

    def _setup_ui(self):
        self.resize(480, 560)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabecera = QFrame()
        cabecera.setStyleSheet("QFrame { background: #1B2B4E; border: none; } QLabel { background: transparent; }")
        lay_cab = QVBoxLayout(cabecera)
        lay_cab.setContentsMargins(20, 14, 20, 14)
        lay_cab.setSpacing(0)
        titulo = QLabel("Costos y UF")
        titulo.setStyleSheet("color: white; font-size: 16px; font-weight: 800;")
        subtitulo = QLabel("El precio de cada plan es su multiplicador por el valor de la UF.")
        subtitulo.setStyleSheet("color: #B8C2D6; font-size: 11px;")
        lay_cab.addWidget(titulo)
        lay_cab.addWidget(subtitulo)
        raiz.addWidget(cabecera)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self._QSS_TABS)
        self.tabs.addTab(self._construir_valores(), "Valores")
        self.tabs.addTab(self._construir_modificar(), "Modificar")
        raiz.addWidget(self.tabs, 1)

        self.pie = QStackedWidget()
        self.pie.setStyleSheet("QStackedWidget { background: #F5F7FB; border-top: 1px solid #E1E7F0; }")
        self.pie.addWidget(self._pie([("Cerrar", self._QSS_BTN_SEC, self.reject)]))
        self.pie.addWidget(self._pie([("Cancelar", self._QSS_BTN_SEC, self.reject),
                                      (" Guardar cambios", self._QSS_BTN_PRIM, self.save_and_close)]))
        raiz.addWidget(self.pie)
        self.tabs.currentChanged.connect(self.pie.setCurrentIndex)

    def _pie(self, botones):
        marco = QWidget()
        lay = QHBoxLayout(marco)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(8)
        lay.addStretch()
        for texto, estilo, accion in botones:
            boton = QPushButton(texto)
            boton.setStyleSheet(estilo)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            if "Guardar" in texto:
                boton.setIcon(ThemeManager.icon('fa5s.save', color='white'))
            boton.clicked.connect(accion)
            lay.addWidget(boton)
        return marco

    # ----------------------------------------------------------- pestaña Valores
    def _construir_valores(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)

        self.lbl_resumen = QLabel("")
        self.lbl_resumen.setWordWrap(True)
        self.lbl_resumen.setStyleSheet("color: #14213D; font-size: 12px; font-weight: 700; background: transparent;")
        lay.addWidget(self.lbl_resumen)

        self.grid_valores = QGridLayout()
        self.grid_valores.setHorizontalSpacing(10)
        self.grid_valores.setVerticalSpacing(6)
        self.grid_valores.setColumnStretch(0, 4)
        self.grid_valores.setColumnStretch(1, 2)
        self.grid_valores.setColumnStretch(2, 3)
        for col, texto in enumerate(("PLAN", "UF", "PRECIO MENSUAL")):
            self.grid_valores.addWidget(self._encabezado_columna(texto, derecha=col == 2), 0, col)
        contenedor = QWidget()
        lay_tabla = QVBoxLayout(contenedor)
        lay_tabla.setContentsMargins(0, 0, 4, 0)
        lay_tabla.addLayout(self.grid_valores)
        lay_tabla.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QWidget#contenedorValores { background: transparent; }")
        contenedor.setObjectName("contenedorValores")
        scroll.setWidget(contenedor)
        lay.addWidget(scroll, 1)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaCalculo")
        tarjeta.setStyleSheet("QFrame#tarjetaCalculo { background: #F5F7FB; border: 1px solid #E1E7F0; border-radius: 12px; }"
                              "QFrame#tarjetaCalculo QLabel { background: transparent; border: none; }")
        lay_t = QVBoxLayout(tarjeta)
        lay_t.setContentsMargins(12, 10, 12, 12)
        lay_t.setSpacing(8)
        lay_t.addWidget(self._titulo("PRECIO CON COMPLEMENTOS"))
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.cmb_calc_plan = ComboTarjeta("Plan")
        self.cmb_calc_plan.setStyleSheet(self._QSS_COMBO)
        self.cmb_calc_plan.currentIndexChanged.connect(self._recalcular_calculo)
        self.cmb_calc_comp = ComboMultiple("Complementos", catalogos_service.complementos())
        self.cmb_calc_comp.setStyleSheet(self._QSS_COMBO)
        self.cmb_calc_comp.cambiado.connect(self._recalcular_calculo)
        fila.addWidget(self.cmb_calc_plan, 1)
        fila.addWidget(self.cmb_calc_comp, 1)
        lay_t.addLayout(fila)
        self.lbl_calculo = QLabel("")
        self.lbl_calculo.setWordWrap(True)
        self.lbl_calculo.setStyleSheet("color: #14213D; font-size: 13px; font-weight: 800;")
        lay_t.addWidget(self.lbl_calculo)
        nota = QLabel("Los planes con complementos se calculan solos: no se editan.")
        nota.setStyleSheet("color: #6B7A93; font-size: 11px;")
        lay_t.addWidget(nota)
        lay.addWidget(tarjeta)
        return pagina

    # --------------------------------------------------------- pestaña Modificar
    def _construir_modificar(self):
        contenedor = QWidget()
        contenedor.setObjectName("contenedorModificar")
        contenedor.setStyleSheet("QWidget#contenedorModificar { background: transparent; }")
        lay = QVBoxLayout(contenedor)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)

        lay.addWidget(self._titulo("VALOR UF"))
        fila_uf = QHBoxLayout()
        fila_uf.setSpacing(8)
        self.input_uf = QLineEdit()
        self.input_uf.setStyleSheet(self._QSS_CAMPO)
        self.input_uf.setPlaceholderText("Valor de la UF en pesos")
        self.btn_fetch_uf = QPushButton(" Obtener UF web")
        self.btn_fetch_uf.setIcon(ThemeManager.icon('fa5s.globe', color='white'))
        self.btn_fetch_uf.setStyleSheet(self._QSS_BTN_PRIM)
        self.btn_fetch_uf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fetch_uf.clicked.connect(self.fetch_uf_web)
        fila_uf.addWidget(self.input_uf, 1)
        fila_uf.addWidget(self.btn_fetch_uf)
        lay.addLayout(fila_uf)

        lay.addWidget(self._titulo("COMPLEMENTOS (UF)"))
        self.grid_complementos = QGridLayout()
        self.grid_complementos.setHorizontalSpacing(10)
        self.grid_complementos.setVerticalSpacing(6)
        lay.addLayout(self.grid_complementos)

        lay.addWidget(self._titulo("PLANES (MULTIPLICADOR UF)"))
        self.grid_planes = QGridLayout()
        self.grid_planes.setHorizontalSpacing(10)
        self.grid_planes.setVerticalSpacing(6)
        lay.addLayout(self.grid_planes)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #FFFFFF; }")
        contenedor.setStyleSheet("QWidget#contenedorModificar { background: #FFFFFF; }")
        scroll.setWidget(contenedor)
        return scroll

    # ------------------------------------------------------------------- UF web
    def fetch_uf_web(self):
        self.btn_fetch_uf.setEnabled(False)
        self.btn_fetch_uf.setText(" Buscando...")
        self.uf_worker = FetchUfWorker()
        self.uf_worker.uf_fetched.connect(self._on_uf_fetched)
        self.uf_worker.error_signal.connect(self._on_uf_error)
        self.uf_worker.start()

    def _on_uf_fetched(self, valor_uf):
        self.input_uf.setText(_texto_numero(valor_uf))
        self.btn_fetch_uf.setText(" Obtener UF web")
        self.btn_fetch_uf.setEnabled(True)

    def _on_uf_error(self, error):
        self.btn_fetch_uf.setText(" Obtener UF web")
        self.btn_fetch_uf.setEnabled(True)
        QMessageBox.warning(self, "Error de Conexión", f"No se pudo obtener la UF de internet:\n{error}\nPuedes ingresarla manualmente.")

    # ------------------------------------------------------------------ cálculo
    @staticmethod
    def _numero(texto):
        try:
            return float(str(texto).replace(',', '.'))
        except ValueError:
            return None

    def _es_derivado(self, nombre):
        """True si el nombre es un plan base más complementos conocidos ('Medio + CIV + SZ')."""
        partes = [p.strip() for p in str(nombre).upper().split("+")]
        return len(partes) > 1 and all(p in self._codigos for p in partes[1:])

    def _valores_actuales(self):
        """(uf, {código de complemento: UF}, {plan base en mayúsculas: multiplicador}) con lo escrito en las casillas."""
        uf = self._numero(self.input_uf.text()) or 0.0
        complementos = {c['codigo']: (self._numero(c['input'].text()) or 0.0) for c in self._complementos}
        planes = {p['nombre'].upper(): (self._numero(p['input'].text()) or 0.0) for p in self._planes}
        return uf, complementos, planes

    def _multiplicador_de(self, nombre, planes, complementos):
        """Multiplicador del plan `nombre` ('Medio' o 'Medio + CIV'): el valor escrito a mano en la hoja Planes
        si lo hay, y si no el del plan base más los complementos."""
        if nombre.upper() in self._override:
            return self._override[nombre.upper()]
        partes = [p.strip() for p in nombre.upper().split("+")]
        return planes.get(partes[0], 0.0) + sum(complementos.get(c, self._valores_hoja.get(c, 0.0)) for c in partes[1:])

    def _refrescar(self, *_):
        uf, complementos, planes = self._valores_actuales()
        partes = [f"UF {_clp(uf)}"]
        for c in self._complementos:
            valor = complementos[c['codigo']]
            partes.append(f"{c['nombre']} {_texto_numero(valor)} UF" + ("" if valor > 0 else " (sin valor)"))
        self.lbl_resumen.setText("   ·   ".join(partes))
        for fila in self._filas_valores:
            mult = planes.get(fila['nombre'].upper(), 0.0)
            fila['lbl_mult'].setText(_texto_numero(mult))
            fila['lbl_precio'].setText(_clp(mult * uf))
        self._recalcular_calculo()

    def _recalcular_calculo(self, *_):
        plan = self.cmb_calc_plan.currentText()
        if not plan:
            self.lbl_calculo.setText("")
            return
        uf, complementos, planes = self._valores_actuales()
        nombre = catalogos_service.armar_tipo_servicio(plan, self.cmb_calc_comp.seleccion())
        mult = self._multiplicador_de(nombre, planes, complementos)
        self.lbl_calculo.setText(f"{nombre}:  {_texto_numero(mult)} UF  →  {_clp(mult * uf)}")

    # -------------------------------------------------------------------- datos
    def load_current_data(self):
        uf, _civ = self.data_manager.get_variables()
        self._valores_hoja = self.data_manager.get_valores_complemento()
        self.input_uf.setText(_texto_numero(uf))

        for fila, (codigo, nombre) in enumerate(catalogos_service.complementos()):
            entrada = QLineEdit(_texto_numero(self._valores_hoja.get(codigo, 0.0)))
            entrada.setStyleSheet(self._QSS_CAMPO)
            entrada.textChanged.connect(self._refrescar)
            self.grid_complementos.addWidget(self._etiqueta(nombre), fila // 2 * 2, fila % 2)
            self.grid_complementos.addWidget(entrada, fila // 2 * 2 + 1, fila % 2)
            self._complementos.append({'codigo': codigo, 'nombre': nombre, 'input': entrada})

        planes_data = self.data_manager.get_costos()
        base_por_nombre = {str(p['nombre']).strip().upper(): p.get('uf_mult', 0) for p in planes_data}
        self._filas_valores = []
        fila_valores = 1
        indice = 0
        for plan_data in planes_data:
            nombre = str(plan_data['nombre']).strip()
            mult_val = plan_data.get('uf_mult', 0) or 0
            if self._es_derivado(nombre):
                partes = [p.strip() for p in nombre.upper().split("+")]
                esperado = base_por_nombre.get(partes[0], 0) + sum(self._valores_hoja.get(c, 0.0) for c in partes[1:])
                if abs(mult_val - esperado) > 1e-6:
                    self._override[nombre.upper()] = mult_val
                continue
            entrada = QLineEdit(_texto_numero(mult_val))
            entrada.setStyleSheet(self._QSS_CAMPO)
            entrada.textChanged.connect(self._refrescar)
            self.grid_planes.addWidget(self._etiqueta(nombre), indice // 3 * 2, indice % 3)
            self.grid_planes.addWidget(entrada, indice // 3 * 2 + 1, indice % 3)
            self._planes.append({'nombre': nombre, 'input': entrada})
            lbl_nombre = QLabel(nombre)
            lbl_nombre.setStyleSheet("color: #14213D; font-size: 12px; font-weight: 800; background: transparent; border: none;")
            lbl_mult = QLabel("")
            lbl_mult.setStyleSheet("color: #14213D; font-size: 12px; background: transparent; border: none;")
            lbl_precio = QLabel("")
            lbl_precio.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_precio.setStyleSheet("color: #14213D; font-size: 13px; font-weight: 800; background: transparent; border: none;")
            self.grid_valores.addWidget(lbl_nombre, fila_valores, 0)
            self.grid_valores.addWidget(lbl_mult, fila_valores, 1)
            self.grid_valores.addWidget(lbl_precio, fila_valores, 2)
            self._filas_valores.append({'nombre': nombre, 'lbl_mult': lbl_mult, 'lbl_precio': lbl_precio})
            fila_valores += 1
            indice += 1
            self.cmb_calc_plan.addItem(nombre)
        self.input_uf.textChanged.connect(self._refrescar)
        self._refrescar()

    def save_and_close(self):
        try:
            import openpyxl
            writer_backup = ExcelWriter()
            writer_backup._crear_backup(config.settings.PROVISION_EXCEL_PATH)
            if not writer_backup.last_backup_ok:
                QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad de provisionFelipe.xlsx. La operación fue cancelada y no se realizó ningún cambio.")
                return
            valores = {"UF": provisiones_services.parsear_numero_uf(self.input_uf.text())}
            for c in self._complementos:
                texto = c['input'].text().strip()
                valores[c['codigo']] = provisiones_services.parsear_numero_uf(texto) if texto else 0.0
            multiplicadores = {p['nombre']: provisiones_services.parsear_numero_uf(p['input'].text()) for p in self._planes}

            wb = openpyxl.load_workbook(config.settings.PROVISION_EXCEL_PATH)
            if "Variables" in wb.sheetnames:
                provisiones_services.escribir_variables_en_hoja(wb["Variables"], valores)

            if "Planes" in wb.sheetnames:
                ws_planes = wb["Planes"]
                for nombre, mult in multiplicadores.items():
                    for row in range(1, 20):
                        if str(ws_planes.cell(row=row, column=1).value).strip() == nombre:
                            ws_planes.cell(row=row, column=2).value = mult
                            break

            dm = self.data_manager
            dm.is_app_saving = True
            dm.save_timestamp = time.time()

            wb.save(config.settings.PROVISION_EXCEL_PATH)
            wb.close()

            dm.load_provisiones_async()
            if not writer_backup.last_backup_ok:
                QMessageBox.warning(self, "Aviso", "Los valores se guardaron, pero no se pudo crear la copia de seguridad previa. Revisa 'Estado del Sistema' en Configuración.")
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Formato Inválido", "Por favor ingresa solo números en las casillas.")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
