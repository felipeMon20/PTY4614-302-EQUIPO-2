"""Panel de "Generar facturación del mes": muestra el avance mientras se crean las carpetas con el
PDF y el Excel de cada razón social y, al terminar, el resumen con lo que falta."""
import os

import qtawesome as qta
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from src.services import facturacion_manual_service as fm_service
from src.theme.colors import DANGER, PRIMARY, SUCCESS
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.facturacion_manual import excel as fm_excel
from src.ui.facturacion_manual import pdf as fm_pdf
_SIN_FONDO = "border: none; background: transparent;"
_AMBAR = ("#FEF3C7", "#92400E")
_ROJO = ("#FEE2E2", "#991B1B")
_VERDE = ("#D1FAE5", "#065F46")
_AZUL = ("#DBE7FE", PRIMARY)
_PASO_ANIMACION_MS = 16
_RAPIDEZ_BARRA = 0.16
_ESCALA_BARRA = 1000


def _boton(texto, primario=False, icono=None):
    btn = QPushButton(f" {texto}" if icono else texto)
    if icono:
        btn.setIcon(qta.icon(icono, color="white" if primario else estilo_com.TINTA))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primario:
        qss = (f"QPushButton {{ background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; }}"
               "QPushButton:hover { background: #1D4ED8; border-color: #1D4ED8; }")
    else:
        qss = (f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; }}"
               f"QPushButton:hover {{ background: {estilo_com.SUPERFICIE_2}; }}")
    btn.setStyleSheet(qss.replace("QPushButton {", "QPushButton { border-radius: 8px; padding: 8px 18px; "
                                  "font-size: 13px; font-weight: 600;", 1))
    return btn


def _icono_circulo(nombre, color_fondo, lado=44):
    icono = QLabel()
    icono.setFixedSize(lado, lado)
    icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icono.setPixmap(qta.icon(nombre, color="white").pixmap(lado // 2, lado // 2))
    icono.setStyleSheet(f"background: {color_fondo}; border-radius: {lado // 2}px; border: none;")
    return icono


def _chip(texto, colores):
    chip = QLabel(texto)
    chip.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {colores[1]}; background: {colores[0]}; "
                       "border-radius: 9px; padding: 3px 10px; border: none;")
    return chip


class _Cifra(QFrame):
    """Tarjeta pequeña con un número grande y su descripción."""

    def __init__(self, valor, texto, colores):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {colores[0]}; border-radius: 10px; border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        numero = QLabel(str(valor))
        numero.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {colores[1]}; {_SIN_FONDO}")
        etiqueta = QLabel(texto)
        etiqueta.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {colores[1]}; {_SIN_FONDO}")
        lay.addWidget(numero)
        lay.addWidget(etiqueta)


class _FilaPendiente(QFrame):
    def __init__(self, cliente, flota, motivo, error):
        super().__init__()
        colores = _ROJO if error or motivo.startswith("sin registro") else _AMBAR
        self.setStyleSheet(f"QFrame {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA_SUAVE}; border-radius: 9px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        punto = QLabel()
        punto.setFixedSize(8, 8)
        punto.setStyleSheet(f"background: {colores[1]}; border-radius: 4px; border: none;")
        textos = QVBoxLayout()
        textos.setSpacing(1)
        nombre = QLabel(str(cliente))
        nombre.setWordWrap(True)
        nombre.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        detalle = QLabel(f"Flota {flota}")
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        textos.addWidget(nombre)
        textos.addWidget(detalle)
        etiqueta = _chip(("Error: " if error else "") + (motivo[:1].upper() + motivo[1:] if motivo else "sin detalle"), colores)
        if len(motivo) > 26:
            etiqueta.setWordWrap(True)
            etiqueta.setMaximumWidth(260)
        lay.addWidget(punto, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(textos, 1)
        lay.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignVCenter)


class PanelFacturacionMes(QDialog):
    """Genera, una tarea por vuelta del event loop (PDF y Excel por separado), la carpeta
    "facturacion MM_AAAA/<flota>/" y anima el porcentaje para que avance con fluidez. Con `agrupar`
    cada flota lleva un PDF y un Excel con todas sus razones sociales; sin agrupar, uno por razón social."""

    def __init__(self, padre, razones, preparar, raiz, etiqueta_periodo, agrupar=True):
        super().__init__(padre)
        self._razones = list(razones)
        self._agrupar = agrupar
        self._unidades = self._armar_unidades()
        self._nombres_usados = set()
        self._preparar = preparar
        self._raiz = raiz
        self._periodo = etiqueta_periodo
        self._generadas = []
        self._faltan = []
        self._fallidas = []
        self._carpetas_usadas = set()
        self._salidas = {}
        self._indice = 0
        self._tareas_hechas = 0
        self._tareas_total = max(1, len(self._unidades) * 2)
        self._cancelado = False
        self._terminado = False
        self._visible = 0.0
        self._actual = None

        self.setWindowTitle("Facturación del mes")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.CustomizeWindowHint)
        self.setFixedWidth(640)
        self.setStyleSheet(f"QDialog {{ background: {estilo_com.SUPERFICIE}; }}")
        raiz_lay = QVBoxLayout(self)
        raiz_lay.setContentsMargins(26, 24, 26, 20)
        self._paginas = QStackedWidget()
        self._paginas.addWidget(self._pagina_progreso())
        self._paginas.addWidget(QWidget())
        raiz_lay.addWidget(self._paginas)

        self._animacion = QTimer(self)
        self._animacion.setInterval(_PASO_ANIMACION_MS)
        self._animacion.timeout.connect(self._animar)
        self._animacion.start()
        QTimer.singleShot(60, self._siguiente_tarea)

    # ------------------------------------------------------------ progreso
    def _pagina_progreso(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        cab = QHBoxLayout()
        cab.setSpacing(14)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel("Generando la facturación del mes")
        titulo.setStyleSheet(f"font-size: 17px; font-weight: 800; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        sub = QLabel(f"{self._periodo} · un PDF y un Excel por {'flota' if self._agrupar else 'razón social'}")
        sub.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        cab.addWidget(_icono_circulo('fa5s.folder-open', PRIMARY, 46))
        cab.addLayout(textos, 1)
        self.lbl_porcentaje = QLabel("0 %")
        self.lbl_porcentaje.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {PRIMARY}; {_SIN_FONDO}")
        self.lbl_porcentaje.setMinimumWidth(96)
        self.lbl_porcentaje.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        cab.addWidget(self.lbl_porcentaje)
        lay.addLayout(cab)

        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setRange(0, _ESCALA_BARRA)
        self.barra.setStyleSheet(
            f"QProgressBar {{ background: {estilo_com.LINEA_SUAVE}; border: none; border-radius: 6px; min-height: 12px; max-height: 12px; }}"
            "QProgressBar::chunk { border-radius: 6px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 #3B82F6, stop:1 {PRIMARY}); }}")
        lay.addWidget(self.barra)

        self.lbl_actual = QLabel("Preparando…")
        self.lbl_actual.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        self.lbl_cuenta = QLabel()
        self.lbl_cuenta.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lay.addWidget(self.lbl_actual)
        lay.addWidget(self.lbl_cuenta)

        botones = QHBoxLayout()
        botones.addStretch(1)
        self.btn_cancelar = _boton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)
        botones.addWidget(self.btn_cancelar)
        lay.addLayout(botones)
        self._actualizar_cuenta()
        return pagina

    def _armar_unidades(self):
        """Trabajos de la generación: uno por flota si se agrupa, o uno por razón social (dentro de la
        carpeta de su flota) si no."""
        flotas = {}
        for r in self._razones:
            flotas.setdefault(r["GRUPO"], []).append(r)
        if self._agrupar:
            return [{"flota": rs[0]["FLOTA"], "razones": rs} for rs in flotas.values()]
        return [{"flota": r["FLOTA"], "razones": [r]} for rs in flotas.values() for r in rs]

    def _actualizar_cuenta(self):
        self.lbl_cuenta.setText(
            f"{len(self._generadas)} generadas · {len(self._faltan) + len(self._fallidas)} por realizar · "
            f"{len(self._razones)} razones sociales en total")

    def _animar(self):
        objetivo = min(1.0, self._tareas_hechas / self._tareas_total)
        self._visible += (objetivo - self._visible) * _RAPIDEZ_BARRA
        if objetivo - self._visible < 0.0008:
            self._visible = objetivo
        self.barra.setValue(round(self._visible * _ESCALA_BARRA))
        self.lbl_porcentaje.setText(f"{int(self._visible * 100 + 0.0001)} %")
        if self._terminado and self._visible >= 1.0 and self._paginas.currentIndex() == 0:
            self._animacion.stop()
            QTimer.singleShot(250, self._mostrar_resumen)

    # ------------------------------------------------------------ trabajo
    def _cancelar(self):
        self._cancelado = True
        self.btn_cancelar.setEnabled(False)
        self.btn_cancelar.setText("Cancelando…")

    def _siguiente_tarea(self):
        if self._indice >= len(self._unidades) or (self._cancelado and self._actual is None):
            self._terminar()
            return
        u = self._unidades[self._indice]
        if self._actual is None:
            self.lbl_actual.setText(f"{u['flota']}" if self._agrupar else f"{u['razones'][0]['CLIENTE']}")
            self._actual = self._abrir(u)
            if self._actual is None:
                self._tareas_hechas += 2
                self._avanzar()
                return
            QTimer.singleShot(0, self._siguiente_tarea)
            return
        paso = self._actual
        varias = len(paso["datos"]) > 1
        try:
            if "pdf" in paso["pendientes"]:
                paso["pendientes"].remove("pdf")
                ruta = os.path.join(paso["carpeta"], paso["nombre"] + ".pdf")
                paso["rutas"].append(ruta)
                if varias:
                    fm_pdf.generar_pdf_flota(ruta, paso["flota"], paso["datos"])
                else:
                    fm_pdf.generar_pdf(ruta, paso["datos"][0])
            else:
                paso["pendientes"].remove("excel")
                ruta = os.path.join(paso["carpeta"], paso["nombre"] + ".xlsx")
                paso["rutas"].append(ruta)
                if varias:
                    fm_excel.generar_excel_flota(ruta, paso["datos"])
                else:
                    fm_excel.generar_excel(ruta, paso["datos"][0])
        except Exception as e:
            for r in paso["razones"]:
                self._fallidas.append((r["CLIENTE"], r["FLOTA"], str(e)))
            self._tareas_hechas += len(paso["pendientes"]) + 1
            self._actual = None
            self._avanzar()
            return
        self._tareas_hechas += 1
        if not paso["pendientes"]:
            self._generadas.extend(r["CLIENTE"] for r in paso["razones"])
            self._anotar_salida(paso)
            self._actual = None
            self._avanzar()
            return
        QTimer.singleShot(0, self._siguiente_tarea)

    def _abrir(self, u):
        """Prepara la carpeta de la flota y los datos de sus razones sociales; None si no se puede generar
        ninguna. Las razones sin lo necesario quedan anotadas como pendientes."""
        razones, datos_lista = [], []
        for r in u["razones"]:
            if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM:
                self._faltan.append((r["CLIENTE"], r["FLOTA"], "sin registro del mes"))
                continue
            try:
                datos, motivo = self._preparar(r)
            except Exception as e:
                datos, motivo = None, str(e) or "no se pudo preparar"
            if datos is None:
                self._faltan.append((r["CLIENTE"], r["FLOTA"], motivo))
                continue
            razones.append(r)
            datos_lista.append(datos)
        if not datos_lista:
            return None
        nombre_flota = os.path.splitext(fm_pdf.nombre_sugerido(u["flota"]))[0]
        carpeta = os.path.join(self._raiz, nombre_flota)
        try:
            os.makedirs(carpeta, exist_ok=True)
        except OSError as e:
            for r in razones:
                self._fallidas.append((r["CLIENTE"], r["FLOTA"], str(e)))
            return None
        nombre = nombre_flota if self._agrupar else os.path.splitext(fm_pdf.nombre_sugerido(razones[0]["CLIENTE"]))[0]
        base, n = nombre, 2
        while os.path.join(carpeta, nombre).lower() in self._nombres_usados:
            nombre = f"{base} ({n})"
            n += 1
        self._nombres_usados.add(os.path.join(carpeta, nombre).lower())
        return {"datos": datos_lista, "razones": razones, "flota": u["flota"], "carpeta": carpeta, "nombre": nombre,
                "pendientes": ["pdf", "excel"], "rutas": []}

    def _anotar_salida(self, paso):
        """Deja anotado, por flota, qué archivos se generaron, de qué tipo son sus registros y sus VIN: es lo que usan los correos."""
        grupo = paso["razones"][0]["GRUPO"]
        salida = self._salidas.setdefault(grupo, {"flota": paso["flota"], "archivos": [], "tipos": set(), "vins": set()})
        salida["archivos"].extend(paso["rutas"])
        salida["tipos"].update(str(r.get("TIPO", "")).strip().upper() for r in paso["razones"])
        for datos in paso["datos"]:
            salida["vins"].update(v for v in (str(fila[2]).strip() for fila in datos["filas"]) if v and v.lower() not in ("nan", "none", "-"))

    def _avanzar(self):
        self._indice += 1
        self._actualizar_cuenta()
        QTimer.singleShot(0, self._siguiente_tarea)

    def _terminar(self):
        self._terminado = True
        self._tareas_hechas = self._tareas_total
        self.lbl_actual.setText("Listo")
        self.btn_cancelar.setVisible(False)

    # ------------------------------------------------------------ resumen
    def _mostrar_resumen(self):
        pendientes = [(c, f, m, False) for c, f, m in self._faltan] + [(c, f, m, True) for c, f, m in self._fallidas]
        completo = not pendientes and not self._cancelado
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        cab = QHBoxLayout()
        cab.setSpacing(14)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        if self._cancelado:
            titulo_texto, icono, fondo = "Generación cancelada", 'fa5s.pause', "#F59E0B"
        elif completo:
            titulo_texto, icono, fondo = "Facturación del mes lista", 'fa5s.check', SUCCESS
        else:
            titulo_texto, icono, fondo = "Facturación generada con pendientes", 'fa5s.exclamation', "#F59E0B"
        titulo = QLabel(titulo_texto)
        titulo.setStyleSheet(f"font-size: 17px; font-weight: 800; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        sub = QLabel(self._periodo)
        sub.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        cab.addWidget(_icono_circulo(icono, fondo, 46))
        cab.addLayout(textos, 1)
        lay.addLayout(cab)

        cifras = QHBoxLayout()
        cifras.setSpacing(10)
        cifras.addWidget(_Cifra(len(self._generadas), "Razones generadas", _VERDE))
        cifras.addWidget(_Cifra(len(self._faltan), "Por realizar", _AMBAR))
        if self._fallidas:
            cifras.addWidget(_Cifra(len(self._fallidas), "Con error", _ROJO))
        sin_intentar = sum(len(u["razones"]) for u in self._unidades[self._indice:])
        if self._cancelado and sin_intentar > 0:
            cifras.addWidget(_Cifra(sin_intentar, "Sin revisar", _AZUL))
        lay.addLayout(cifras)

        carpeta = QLabel(f"<span style='color:{estilo_com.APAGADO};'>Carpeta:</span> {self._raiz}")
        carpeta.setWordWrap(True)
        carpeta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        carpeta.setStyleSheet(f"font-size: 11px; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        lay.addWidget(carpeta)

        if self._salidas:
            lay.addWidget(self._tarjeta_correos())

        if pendientes:
            encabezado = QLabel(f"Faltan {len(pendientes)} por realizar")
            encabezado.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
            lay.addWidget(encabezado)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            area.viewport().setStyleSheet("background: transparent;")
            contenido = QWidget()
            contenido.setStyleSheet("background: transparent;")
            filas = QVBoxLayout(contenido)
            filas.setContentsMargins(0, 0, 6, 0)
            filas.setSpacing(6)
            for cliente, flota, motivo, error in pendientes:
                filas.addWidget(_FilaPendiente(cliente, flota, motivo, error))
            filas.addStretch(1)
            area.setWidget(contenido)
            disponible = self.screen().availableGeometry().height() if self.screen() else 800
            area.setFixedHeight(min(300, 58 * len(pendientes) + 6, max(120, disponible - 580)))
            lay.addWidget(area)
        elif completo:
            ok = QLabel("No falta ninguna: todas las razones sociales del período quedaron generadas.")
            ok.setWordWrap(True)
            ok.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
            lay.addWidget(ok)

        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addStretch(1)
        cerrar = _boton("Cerrar")
        cerrar.clicked.connect(self.accept)
        abrir = _boton("Abrir carpeta", primario=True, icono='fa5s.folder-open')
        abrir.clicked.connect(self._abrir_carpeta)
        abrir.setEnabled(os.path.isdir(self._raiz))
        botones.addWidget(cerrar)
        botones.addWidget(abrir)
        lay.addLayout(botones)

        anterior = self._paginas.widget(1)
        self._paginas.removeWidget(anterior)
        anterior.deleteLater()
        self._paginas.addWidget(pagina)
        self._paginas.setCurrentWidget(pagina)
        self.adjustSize()
        self._centrar()

    def _centrar(self):
        pantalla = self.screen()
        if pantalla is None:
            return
        zona = pantalla.availableGeometry()
        self.setMaximumHeight(zona.height() - 40)
        if self.height() > zona.height() - 40:
            self.resize(self.width(), zona.height() - 40)
        marco = self.frameGeometry()
        marco.moveCenter(zona.center())
        self.move(marco.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        self._centrar()

    def _abrir_carpeta(self):
        if os.path.isdir(self._raiz):
            os.startfile(self._raiz)

    def _tarjeta_correos(self):
        """Pregunta si se envían los archivos al correo del administrador de cada flota."""
        tarjeta = QFrame()
        tarjeta.setStyleSheet(f"QFrame {{ background: #F4F7FB; border: 1px solid {estilo_com.LINEA_SUAVE}; border-radius: 12px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        pregunta = QLabel("¿Quieres enviar los archivos al correo del administrador de cada flota?")
        pregunta.setWordWrap(True)
        pregunta.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        ayuda = QLabel("Se abre una ventana para revisar los correos antes de enviarlos.")
        ayuda.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lay.addWidget(pregunta)
        lay.addWidget(ayuda)
        fila = QHBoxLayout()
        fila.addStretch(1)
        no = _boton("Ahora no")
        no.clicked.connect(tarjeta.hide)
        si = _boton("Sí, preparar correos", primario=True, icono='fa5s.envelope')
        si.clicked.connect(self._preparar_correos)
        fila.addWidget(no)
        fila.addWidget(si)
        lay.addLayout(fila)
        return tarjeta

    def _preparar_correos(self):
        from src.ui.facturacion_manual.correos_dialogo import DialogoCorreosFacturacion
        DialogoCorreosFacturacion(self, self._salidas.values(), self._periodo).exec()

    def reject(self):
        if self._paginas.currentIndex() == 1:
            self.accept()
        else:
            self._cancelar()
