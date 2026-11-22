import csv
import html
import os

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import qtawesome as qta
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
                             QPushButton, QMessageBox, QLineEdit, QTabWidget, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from src.core.data_manager import DataManager
from src.core.hilos import iniciar_hilo_retenido
from src.core.excel_writer import ExcelWriter
from src.services import copias_conflicto
from src.ui.administracion import estilo as admin_estilo
from src.ui.administracion import listas as admin_listas
from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
import openpyxl
import config.settings

# Antigüedad desde la que el botón de limpiar borra, en el historial de
# modificaciones y en la Papelera
DIAS_RETENCION_LOG = 30


def _es_mas_antigua(valor, limite):
    """True si la fecha y hora del registro (texto 'aaaa-mm-dd hh:mm:ss' o
    datetime) es anterior a `limite`; una fecha ilegible nunca cuenta como
    antigua, para no borrar un registro sin saber de cuándo es."""
    if isinstance(valor, datetime):
        return valor < limite
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d %H:%M:%S") < limite
    except ValueError:
        return False


def _a_fecha(serie, formato, **opciones):
    """to_datetime con un formato fijo; solo lo que no calce pasa por el
    análisis elemento a elemento ('mixed' con dayfirst), que es lento."""
    fechas = pd.to_datetime(serie, format=formato, errors='coerce')
    faltan = fechas.isna() & serie.notna()
    if faltan.any():
        fechas[faltan] = pd.to_datetime(serie[faltan], format='mixed', errors='coerce', **opciones)
    return fechas


class _ComparadorCopias(QThread):
    """Compara en segundo plano cada copia de conflicto con su original (lee ambos archivos completos)."""
    terminado = pyqtSignal(int)

    def __init__(self, copias, generacion):
        super().__init__()
        self._copias = [dict(c) for c in copias]
        self._generacion = generacion
        self.resultados = {}

    def run(self):
        for c in self._copias:
            try:
                self.resultados[c["copia"]] = copias_conflicto.comparar_cacheado(c)
            except Exception as e:
                self.resultados[c["copia"]] = {"error": f"No se pudo comparar: {e}", "sin_original": False,
                                               "nivel": "revisar", "veredicto": ""}
        self.terminado.emit(self._generacion)


class _Cambios:
    """Filas de un guardado dentro de un día. El DataFrame con sus filas solo se arma al abrir el
    detalle: un día puede tener más de mil guardados y casi ninguno se despliega."""
    __slots__ = ("base", "_posiciones", "_filas")

    def __init__(self, base, posiciones):
        self.base = base
        self._posiciones = posiciones
        self._filas = None

    def __len__(self):
        return len(self._posiciones)

    @property
    def filas(self):
        if self._filas is None:
            self._filas = self.base.iloc[self._posiciones]
        return self._filas


class HistorialModule(QWidget):
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        # Actualizacion diferida por visibilidad (mismo mecanismo que
        # general.py/comercial.py): data_ready mientras esta oculto solo
        # marca dirty, no reprocesa. logs_updated NO pasa por este mecanismo
        # -- sigue conectado directo a load_data para mantener su refresco
        # inmediato existente (ver comentario original mas abajo).
        #
        # Fase 1 de la auditoria de rendimiento (17-09-2026): se evaluo
        # aplicar aqui el mismo guard de visibilidad a logs_updated, pero se
        # revirtio -- existe un test dedicado (test_dirty_refresh.py,
        # TestHistorialDualSenal.test_logs_updated_no_espera_visibilidad_ni_dirty)
        # que documenta que esto es una decision de diseño intencional: logs_updated
        # debe seguir refrescando de inmediato sin pasar por el dirty flag,
        # a diferencia de data_ready. No se toca.
        self._data_dirty = False
        self.data_manager.data_ready.connect(self._on_data_ready)
        # logs_updated: refresco ligero especifico del historial (ej. tras
        # una sincronizacion que solo escribio en LogApp.csv), sin esperar
        # a una recarga completa via data_ready. Ver DataManager.set_logs_df.
        self.data_manager.logs_updated.connect(self.load_data)

        # Receptor invisible para la búsqueda global de main_window.py
        self.search_input = QLineEdit()
        self.search_input.hide()
        
        self._dias_mods, self._dias_del = [], []
        self._tanda_mods = self._tanda_del = self.DIAS_POR_TANDA
        self.filtered_mods = pd.DataFrame()
        self.filtered_del = pd.DataFrame()
        self.df_mods_base = pd.DataFrame()
        self.deleted_sheets_base = {}
        self._papelera_pendiente = True
        self._copias = []
        self._gen_conflictos = 0
        self._hilo_conflictos = None
        self._resultados_hilo = {}

        self._setup_ui()
        self.load_data()

    # El panel azul de Administración queda separado de las cajas de abajo
    ENCABEZADO_SEPARADO = True
    _RANGOS = (("Hoy", "Hoy"), ("7 días", "Últimos 7 días"), ("30 días", "Últimos 30 días"),
               ("Año", "Último Año"), ("Todos", "Todos los tiempos"))

    def _setup_ui(self):
        main_layout = admin_estilo.raiz_pantalla(self)
        cuerpo = QWidget()
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(12)
        fila.addWidget(self._crear_caja_secciones())
        fila.addWidget(self._crear_caja_contenido(), 1)
        main_layout.addWidget(cuerpo, 1)
        self._on_tab_changed()

    def _crear_caja_secciones(self):
        caja = admin_estilo.caja_con_encabezado("cajaSeccionesHistorial", "Historial", "Secciones")
        caja.marco.setFixedWidth(250)
        lay = caja.cuerpo

        self._botones_sec, self._badges_sec = [], []
        lista = QWidget()
        lay_lista = QVBoxLayout(lista)
        lay_lista.setContentsMargins(8, 8, 8, 8)
        lay_lista.setSpacing(4)
        for i, (nombre, icono) in enumerate((("Logs de modificaciones", 'fa5s.history'), ("Papelera", 'fa5s.trash-alt'),
                                        ("Conflictos de copias", 'fa5s.clone'))):
            boton, badge = admin_estilo.boton_seccion(nombre, icono)
            badge.hide()
            boton.clicked.connect(lambda _c, k=i: self.tabs.setCurrentIndex(k))
            lay_lista.addWidget(boton)
            self._botones_sec.append(boton)
            self._badges_sec.append(badge)
        lay.addWidget(lista)

        bloque_filtros = admin_estilo.bloque_caja("Filtros")
        bloque_filtros.layout().addWidget(admin_estilo.etiqueta_caja("Rango"))
        # Mantiene el combo (oculto) como único estado del rango: los botones solo lo cambian
        self.cb_rango_fechas = estilo_com.ComboTarjeta("Rango de tiempo", self)
        self.cb_rango_fechas.addItems([valor for _t, valor in self._RANGOS[-1:] + self._RANGOS[:-1]])
        self.cb_rango_fechas.currentTextChanged.connect(lambda: self.filter_tables(reset_page=True))
        self.cb_rango_fechas.hide()
        grilla = QGridLayout()
        grilla.setContentsMargins(0, 0, 0, 0)
        grilla.setSpacing(6)
        self._botones_rango = {}
        for i, (texto, valor) in enumerate(self._RANGOS):
            boton = admin_estilo.boton_chip(texto)
            boton.clicked.connect(lambda _c, v=valor: self._elegir_rango(v))
            grilla.addWidget(boton, i // 3, i % 3)
            self._botones_rango[valor] = boton
        bloque_filtros.layout().addLayout(grilla)
        self.lbl_papelera_modulo = admin_estilo.etiqueta_caja("Módulo eliminado")
        self.combo_papelera_modulo = estilo_com.ComboTarjeta("Módulo eliminado")
        self.combo_papelera_modulo.currentTextChanged.connect(lambda: self.filter_tables(reset_page=True))
        admin_estilo.combo_barra(self.combo_papelera_modulo, 150, claro=True)
        bloque_filtros.layout().addWidget(self.lbl_papelera_modulo)
        bloque_filtros.layout().addWidget(self.combo_papelera_modulo)
        lay.addWidget(bloque_filtros)
        self._elegir_rango("Todos los tiempos")

        bloque_acciones = admin_estilo.bloque_caja("Acciones")
        self.btn_export_excel = admin_estilo.boton_accion("Exportar a Excel", 'fa5s.file-excel')
        self.btn_export_excel.clicked.connect(self._export_current_tab_excel)
        # Vacía la pestaña activa (LogApp.csv o RegistroEliminado.xlsx) con
        # backup previo y conservando encabezados (ver _clear_logs).
        self.btn_clear = admin_estilo.boton_accion("Limpiar antiguos", 'fa5s.trash-alt', peligro=True)
        self.btn_clear.clicked.connect(self._clear_logs)
        for boton in (self.btn_export_excel, self.btn_clear):
            bloque_acciones.layout().addWidget(boton)
        lay.addWidget(bloque_acciones)
        lay.addStretch(1)
        return caja.marco

    def _crear_caja_contenido(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaContenidoHistorial", "Logs de modificaciones", "")
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.lista_mods = admin_listas.ListaAgrupada()
        self.tabs.addTab(self.lista_mods, "Logs de Modificaciones")
        self.lista_del = admin_listas.ListaAgrupada()
        self.tabs.addTab(self.lista_del, "Papelera (Registros Eliminados)")
        self.lista_conf = admin_listas.ListaAgrupada()
        self.tabs.addTab(self.lista_conf, "Conflictos de copias")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._caja.cuerpo.addWidget(self.tabs, 1)
        return self._caja.marco

    def _elegir_rango(self, valor):
        for v, boton in self._botones_rango.items():
            boton.setChecked(v == valor)
        if self.cb_rango_fechas.currentText() != valor:
            self.cb_rango_fechas.setCurrentText(valor)

    def _actualizar_resumen(self, n_guardados_mods=0, n_guardados_del=0):
        """Contadores de las sub-pestañas y subtítulo según los filtros vigentes."""
        n_m, n_d = len(self.filtered_mods), len(self.filtered_del)
        rango = self.cb_rango_fechas.currentText().lower()
        if self.tabs.currentIndex() == 2:
            self._caja.lbl_subtitulo.setText(admin_listas.plural(len(self._copias), "copia detectada", "copias detectadas"))
        elif self.tabs.currentIndex() == 0:
            self._caja.lbl_subtitulo.setText(f"{n_m} cambios en {n_guardados_mods} guardados · {rango}")
        else:
            self._caja.lbl_subtitulo.setText(f"{n_d} registros eliminados · {rango}")

    def _on_tab_changed(self):
        es_papelera = self.tabs.currentIndex() == 1
        es_conflictos = self.tabs.currentIndex() == 2
        if es_papelera and self._papelera_pendiente:
            self._cargar_papelera()
            self.filter_tables(reset_page=True)
        if es_conflictos:
            self._copias = copias_conflicto.buscar_copias()
            self._resultados_hilo = {}
            self._actualizar_badge_conflictos()
        self.lbl_papelera_modulo.setVisible(es_papelera)
        self.combo_papelera_modulo.setVisible(es_papelera)
        self._caja.lbl_titulo.setText("Conflictos de copias" if es_conflictos
                                      else "Papelera" if es_papelera else "Logs de modificaciones")
        for i, boton in enumerate(self._botones_sec):
            boton.setChecked(i == self.tabs.currentIndex())

        self.btn_export_excel.setEnabled(not es_conflictos)
        self.btn_clear.setText("Eliminar todas" if es_conflictos else "Limpiar antiguos")
        self.btn_clear.setEnabled(not es_conflictos or bool(self._copias))
        if es_conflictos:
            self.btn_clear.setToolTip("Elimina todas las copias de conflicto detectadas, con respaldo previo.")
        elif es_papelera:
            self.btn_clear.setToolTip(f"Elimina los registros de todas las hojas de la Papelera con más de {DIAS_RETENCION_LOG} días, con backup previo.")
        else:
            self.btn_clear.setToolTip(f"Elimina los registros del historial de modificaciones con más de {DIAS_RETENCION_LOG} días, con backup previo.")

        self._pintar()

    # =========================================================
    # FUNCIÓN PARA ELIMINAR EL ARCHIVO EXCEL GIGANTE
    # =========================================================
    def _clear_logs(self):
        if self.tabs.currentIndex() == 2:
            self._eliminar_copias(self._copias)
            return
        is_mods = self.tabs.currentIndex() == 0

        if is_mods:
            self._clear_logs_modificaciones()
            return

        self._clear_papelera()

    def _clear_logs_modificaciones(self):
        # Borra de LogApp.csv solo los registros con más de DIAS_RETENCION_LOG
        # días (con backup previo); los recientes se conservan porque otras
        # pantallas los consultan (ej. el nivel anterior en los correos).
        msg = QMessageBox(self)
        msg.setWindowTitle("Limpiar Logs de Modificaciones")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            f"¿Deseas eliminar los registros del historial de modificaciones con más de {DIAS_RETENCION_LOG} días?\n\n"
            f"Los registros de los últimos {DIAS_RETENCION_LOG} días se conservan."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        filepath = config.settings.LOG_CSV_PATH
        if not filepath or not os.path.exists(filepath):
            QMessageBox.information(self, "Aviso", "El historial de modificaciones no existe o ya está vacío.")
            return

        limite = datetime.now() - timedelta(days=DIAS_RETENCION_LOG)

        try:
            with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
                lector = csv.reader(f)
                encabezado = next(lector, None)
                filas = [fila for fila in lector if any(fila)]
            if not encabezado:
                QMessageBox.information(self, "Aviso", "El historial de modificaciones ya está vacío.")
                return
            conservadas = [fila for fila in filas if not _es_mas_antigua(fila[0], limite)]
            filas_borradas = len(filas) - len(conservadas)
            if filas_borradas == 0:
                QMessageBox.information(self, "Aviso", f"No hay registros con más de {DIAS_RETENCION_LOG} días.")
                return

            if not self.writer._crear_backup(filepath):
                QMessageBox.warning(
                    self, "Error",
                    "No se pudo crear el backup de LogApp.csv antes de limpiarlo. "
                    "Por seguridad, no se eliminó ningún registro. Inténtalo nuevamente."
                )
                return

            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                escritor = csv.writer(f)
                escritor.writerow(encabezado)
                escritor.writerows(conservadas)
        except PermissionError:
            QMessageBox.warning(self, "Error", "El archivo está abierto o bloqueado. Ciérralo e inténtalo de nuevo.")
            return
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Ocurrió un problema: {e}")
            return

        QMessageBox.information(
            self, "Éxito",
            f"Se eliminaron {filas_borradas} registro(s) con más de {DIAS_RETENCION_LOG} días."
        )
        self.data_manager.load_data_async()

    def _clear_papelera(self):
        # Vacía TODAS las hojas de RegistroEliminado.xlsx (una por módulo:
        # Comercial, Provisiones, Contactos, etc.), no solo wb.active. Cada
        # hoja conserva su encabezado y su existencia; solo se descartan las
        # filas de datos. Requiere backup previo exitoso (mismo mecanismo que
        # ya protege el resto de las escrituras sobre este archivo, ver
        # ExcelWriter._log_deleted) antes de borrar nada.
        msg = QMessageBox(self)
        msg.setWindowTitle("Limpiar Papelera")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            f"¿Deseas eliminar los registros de la Papelera con más de {DIAS_RETENCION_LOG} días, "
            "en todos los módulos (Comercial, Provisiones, Contactos, etc.)?\n\n"
            f"Los eliminados en los últimos {DIAS_RETENCION_LOG} días se conservan, "
            "y los encabezados y las hojas quedan intactos."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        filepath = config.settings.DELETED_LOG_EXCEL_PATH
        if not filepath or not os.path.exists(filepath):
            QMessageBox.information(self, "Aviso", "El archivo de la Papelera no existe o ya está vacío.")
            return

        limite = datetime.now() - timedelta(days=DIAS_RETENCION_LOG)
        try:
            wb = openpyxl.load_workbook(filepath)
            antiguas = {
                nombre: [r for r in range(2, wb[nombre].max_row + 1) if _es_mas_antigua(wb[nombre].cell(row=r, column=1).value, limite)]
                for nombre in wb.sheetnames
            }
            filas_borradas = sum(len(filas) for filas in antiguas.values())
            if filas_borradas == 0:
                wb.close()
                QMessageBox.information(self, "Aviso", f"No hay registros con más de {DIAS_RETENCION_LOG} días en la Papelera.")
                return

            if not self.writer._crear_backup(filepath):
                wb.close()
                QMessageBox.warning(
                    self, "Error",
                    "No se pudo crear el backup de RegistroEliminado.xlsx antes de limpiar la Papelera. "
                    "Por seguridad, no se eliminó ningún registro. Inténtalo nuevamente."
                )
                return

            for nombre, filas in antiguas.items():
                for r in reversed(filas):
                    wb[nombre].delete_rows(r)
            wb.save(filepath)
            wb.close()
        except PermissionError:
            QMessageBox.warning(self, "Error", "El archivo está abierto en Excel o bloqueado. Ciérralo e inténtalo de nuevo.")
            return
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Ocurrió un problema: {e}")
            return

        QMessageBox.information(
            self, "Éxito",
            f"Se eliminaron {filas_borradas} registro(s) de la Papelera con más de {DIAS_RETENCION_LOG} días."
        )
        self.data_manager.load_data_async()  # Recargamos la interfaz


    def _eliminar_copias(self, copias):
        if not copias:
            return
        detalle = "\n".join(f"- {c['nombre']}" for c in copias[:10])
        if len(copias) > 10:
            detalle += f"\n... y {len(copias) - 10} más"
        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar copias de conflicto")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f"¿Eliminar {admin_listas.plural(len(copias), 'copia')} de conflicto?\n\n{detalle}\n\n"
                    "Antes de eliminar se guarda un respaldo de cada una.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        errores = []
        for c in copias:
            ok, motivo = copias_conflicto.eliminar(c, self.writer._crear_backup)
            if not ok:
                errores.append(f"{c['nombre']}: {motivo}")
        self._copias = copias_conflicto.buscar_copias()
        self._actualizar_badge_conflictos()
        self._on_tab_changed()
        if errores:
            QMessageBox.warning(self, "Aviso", "No se pudieron eliminar algunas copias:\n\n" + "\n".join(errores))

    def _actualizar_badge_conflictos(self):
        badge = self._badges_sec[2]
        admin_estilo.fijar_badge(badge, len(self._copias))
        badge.setVisible(bool(self._copias))

    _TONO_NIVEL = {"ok": ("Se puede eliminar", "verde"), "viejo": ("Versión antigua", "gris"),
                   "revisar": ("Revisar", "ambar")}

    def _pintar_conflictos(self):
        lista = self.lista_conf
        lista.reiniciar()
        if not self._copias:
            lista.mostrar_vacio("No hay copias de conflicto. Los archivos de datos están al día.")
        # Comparar lee ambos archivos completos (cientos de ms): se hace en segundo plano y
        # lo ya comparado se reutiliza; mientras tanto la fila muestra "Comparando"
        pendientes = []
        for c in self._copias:
            c["resultado"] = copias_conflicto.resultado_en_cache(c) or self._resultados_hilo.get(c["copia"])
            if c["resultado"] is None:
                pendientes.append(c)
        if pendientes:
            self._comparar_en_fondo(pendientes)
        for c in self._copias:
            if c["resultado"] is None:
                fila = admin_listas.Colapsable(constructor=lambda c=c: self._detalle_copia(c), nivel=1)
                fila.agregar(admin_listas.pildora("Comparando…", "gris"))
            else:
                nivel = c["resultado"]["nivel"]
                texto_nivel, tono = self._TONO_NIVEL[nivel]
                fila = admin_listas.Colapsable(constructor=lambda c=c: self._detalle_copia(c), nivel=1, abierto=nivel == "revisar")
                fila.agregar(admin_listas.pildora(texto_nivel, tono))
            fila.agregar(admin_listas.pildora(c["archivo"], "azul"))
            fila.agregar(admin_listas.texto(c["nombre"], tam=12, negrita=True), 1)
            fila.agregar(admin_listas.texto(f"Equipo {c['equipo']}", color=estilo_com.APAGADO, tam=11))
            boton = QPushButton(" Eliminar")
            boton.setIcon(ThemeManager.icon('fa5s.trash-alt', color=estilo_com.ROJO))
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setFixedHeight(28)
            boton.setStyleSheet(
                f"QPushButton {{ background: #FDECEC; color: {estilo_com.ROJO}; border: 1px solid #F5C6C6; "
                "border-radius: 14px; padding: 0 14px; font-size: 12px; font-weight: 700; }"
                f"QPushButton:hover {{ background: {estilo_com.ROJO}; color: white; border: 1px solid {estilo_com.ROJO}; }}")
            boton.enterEvent = lambda e, b=boton: b.setIcon(ThemeManager.icon('fa5s.trash-alt', color="white"))
            boton.leaveEvent = lambda e, b=boton: b.setIcon(ThemeManager.icon('fa5s.trash-alt', color=estilo_com.ROJO))
            boton.clicked.connect(lambda _c, c=c: self._eliminar_copias([c]))
            fila.agregar(boton)
            lista.agregar(fila)
        self._actualizar_resumen()

    def _comparar_en_fondo(self, pendientes):
        self._gen_conflictos += 1
        hilo = _ComparadorCopias(pendientes, self._gen_conflictos)
        hilo.terminado.connect(self._al_comparar_copias)
        self._hilo_conflictos = hilo
        iniciar_hilo_retenido(hilo)

    def _al_comparar_copias(self, generacion):
        # Un resultado de una búsqueda anterior no repinta; la lista ya se rehizo desde entonces
        if generacion == self._gen_conflictos:
            self._resultados_hilo = dict(self._hilo_conflictos.resultados)
            if self.tabs.currentIndex() == 2:
                self._pintar_conflictos()

    def _detalle_copia(self, c):
        marco = QFrame()
        marco.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(52, 0, 16, 10)
        lay.setSpacing(3)
        r = c["resultado"] or copias_conflicto.resultado_en_cache(c)
        if r is None:
            lay.addWidget(admin_listas.texto("Comparando la copia con el original…", color=estilo_com.APAGADO, tam=12))
            return marco
        lay.addWidget(admin_listas.texto(r["error"] or r["veredicto"], tam=13, negrita=True))
        if r["error"] or r["sin_original"]:
            return marco
        fecha_c = datetime.fromtimestamp(c["modificado"]).strftime("%d-%m-%Y %H:%M")
        fecha_o = datetime.fromtimestamp(os.path.getmtime(c["original"])).strftime("%d-%m-%Y %H:%M")
        lay.addWidget(admin_listas.texto(f"Copia: {fecha_c} · Original: {fecha_o}", color=estilo_com.APAGADO, tam=12))

        if r["modo_filas"]:
            lineas = [(r["nuevos_copia"], "fila", "solo está en la copia"),
                      (r["nuevos_original"], "fila", "solo está en el original")]
        else:
            lineas = [(r["nuevos_copia"], "registro", "solo está en la copia"),
                      (r["nuevos_original"], "registro", "solo está en el original"),
                      (r["modificados"], "registro", "está en ambos pero con datos distintos")]
        for n, unidad, que in lineas:
            if n:
                lay.addWidget(admin_listas.texto(f"• {admin_listas.plural(n, unidad, unidad + 's')} {que}", tam=12))
        if r["columnas"]:
            lay.addWidget(admin_listas.texto("Campos que más difieren: " + ", ".join(f"{n} ({k})" for n, k in r["columnas"]),
                                             color=estilo_com.APAGADO, tam=12))
        for titulo, ejemplos in (("Solo en la copia", r["ej_nuevos"]), ("Con datos distintos", r["ej_modificados"])):
            if ejemplos:
                lay.addWidget(admin_listas.texto(titulo + " (ejemplos):", tam=12, negrita=True))
                for e in ejemplos[:3]:
                    lay.addWidget(admin_listas.texto("   " + e, color=estilo_com.APAGADO, tam=11, seleccionable=True))
        return marco
    def _export_current_tab_excel(self):
        if self.tabs.currentIndex() == 2:
            return
        if self.tabs.currentIndex() == 0:
            admin_estilo.exportar_excel(self, self.filtered_mods, "Reporte_Auditoria")
            return
        modulo = self.combo_papelera_modulo.currentText() or "SinModulo"
        admin_estilo.exportar_excel(self, self.filtered_del, f"Reporte_Papelera_{modulo}")

    def _handle_restaurar(self, row, vin):
        # Bloqueado: ExcelWriter no implementa restore_row (nunca se llegó a
        # construir esa funcionalidad). El punto de entrada en la UI
        # (menú contextual "Restaurar Fila" en custom_table.py) ya está
        # deshabilitado; este guardia evita un AttributeError si algo
        # llegara a invocar este método de todas formas.
        QMessageBox.information(
            self, "No disponible",
            "Restaurar un registro desde la Papelera está temporalmente deshabilitado: "
            "todavía no existe un mecanismo de restauración seguro por módulo."
        )

    def _on_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este
        modulo. Sin pending_changes que proteger (vista de solo lectura)."""
        if self._data_dirty:
            self.load_data()

    @staticmethod
    def _formatear_fechas(df):
        """Formato latino (DD-MM-YYYY HH:MM:SS) en la columna de fecha."""
        if df.empty: return df
        col_fecha = next((c for c in df.columns if 'FECHA' in str(c).upper() or 'FECHAHORA' in str(c).upper()), None)
        if col_fecha:
            try:
                df[col_fecha] = pd.to_datetime(df[col_fecha], format='mixed', errors='coerce').dt.strftime('%d-%m-%Y %H:%M:%S').fillna(df[col_fecha])
            except Exception: pass
        return df

    def load_data(self):
        self._data_dirty = False
        self._copias = copias_conflicto.buscar_copias()
        self._resultados_hilo = {}
        self._actualizar_badge_conflictos()
        self.df_mods_base =self._formatear_fechas(self.data_manager.get_logs_df())
        if not self.df_mods_base.empty: self.df_mods_base = self.df_mods_base.iloc[::-1].reset_index(drop=True)

        # La Papelera (RegistroEliminado.xlsx) se lee solo al abrir su pestaña
        self._papelera_pendiente = True
        if self.tabs.currentIndex() == 1 or self.data_manager.papelera_en_memoria():
            self._cargar_papelera()
        self.filter_tables(reset_page=True)

    def _cargar_papelera(self):
        # deleted_sheets_base: {nombre_modulo: DataFrame}, una por hoja de
        # RegistroEliminado.xlsx; cada hoja conserva su propio esquema.
        self._papelera_pendiente = False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.deleted_sheets_base = self.data_manager.get_deleted_logs_sheets()
        finally:
            QApplication.restoreOverrideCursor()
        for nombre_modulo, df_hoja in self.deleted_sheets_base.items():
            df_hoja = self._formatear_fechas(df_hoja)
            if not df_hoja.empty: df_hoja = df_hoja.iloc[::-1].reset_index(drop=True)
            self.deleted_sheets_base[nombre_modulo] = df_hoja
        self._actualizar_combo_papelera_modulo()

    def _actualizar_combo_papelera_modulo(self):
        modulo_previo = self.combo_papelera_modulo.currentText()
        self.combo_papelera_modulo.blockSignals(True)
        self.combo_papelera_modulo.clear()
        nombres_modulos = list(self.deleted_sheets_base.keys())
        if nombres_modulos:
            self.combo_papelera_modulo.addItems(nombres_modulos)
            if modulo_previo in nombres_modulos:
                self.combo_papelera_modulo.setCurrentText(modulo_previo)
        self.combo_papelera_modulo.blockSignals(False)

    # =========================================================
    # LÓGICA DE FILTRADO
    # =========================================================
    def filter_tables(self, reset_page=False):
        search_text = self.search_input.text().lower()
        rango = self.cb_rango_fechas.currentText()
        hoy = pd.Timestamp(datetime.now().date())
        
        # Filtro de conversión matemática de fechas (A prueba de balas)
        def filtrar_por_rango(df, col_fecha):
            if df.empty or col_fecha not in df.columns or rango == "Todos los tiempos":
                return df

            fechas_raw = df[col_fecha].astype(str).str.strip().str.split(" ").str[0]
            df_fechas = pd.to_datetime(fechas_raw, dayfirst=True, errors='coerce')
            
            mask_nat = df_fechas.isna()
            if mask_nat.any():
                df_fechas.loc[mask_nat] = pd.to_datetime(fechas_raw[mask_nat], format='mixed', errors='coerce')
            
            if rango == "Todos los tiempos": return df
            elif rango == "Hoy": return df[df_fechas == hoy]
            elif rango == "Últimos 7 días": return df[df_fechas >= (hoy - pd.Timedelta(days=7))]
            elif rango == "Últimos 30 días": return df[df_fechas >= (hoy - pd.Timedelta(days=30))]
            elif rango == "Último Año": return df[df_fechas >= (hoy - pd.Timedelta(days=365))]
            
            return df

        # 1. Logs de Modificaciones
        df_m = self.df_mods_base.copy()
        if not df_m.empty:
            col_fecha = next((c for c in df_m.columns if 'FECHA' in str(c).upper() or 'FECHAHORA' in str(c).upper()), None)
            df_m = filtrar_por_rango(df_m, col_fecha)
            if search_text:
                mask_search = pd.Series(False, index=df_m.index)
                for col in df_m.columns:
                    mask_search |= df_m[col].astype(str).str.lower().str.contains(search_text, na=False, regex=False)
                df_m = df_m[mask_search]
        self.filtered_mods = df_m

        # 2. Papelera: solo la hoja/modulo seleccionado en combo_papelera_modulo,
        # con sus columnas reales tal cual estan en RegistroEliminado.xlsx —
        # nunca se combina con las de otro modulo.
        modulo_sel = self.combo_papelera_modulo.currentText()
        df_d = self.deleted_sheets_base.get(modulo_sel, pd.DataFrame()).copy()
        if not df_d.empty:
            col_fecha = next((c for c in df_d.columns if 'FECHA' in str(c).upper() or 'FECHAHORA' in str(c).upper()), None)
            if col_fecha:
                df_d = filtrar_por_rango(df_d, col_fecha)
            if search_text:
                mask_search = pd.Series(False, index=df_d.index)
                for col in df_d.columns:
                    mask_search |= df_d[col].astype(str).str.lower().str.contains(search_text, na=False, regex=False)
                df_d = df_d[mask_search]
        self.filtered_del = df_d

        self._pintar()

    # =========================================================
    # VISTA AGRUPADA POR DÍA
    # =========================================================
    DIAS_POR_TANDA = 10
    EVENTOS_POR_TANDA = 80
    _MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    _DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    _TONOS_MODULO = {"COMERCIAL": "verde", "PROVISIONES": "violeta", "OPERACIONES": "azul", "CONTACTOS": "ambar"}

    @staticmethod
    def _col(df, *claves):
        for c in df.columns:
            if any(k in str(c).upper() for k in claves):
                return c
        return None

    def _etiqueta_dia(self, dia):
        hoy = pd.Timestamp(datetime.now().date())
        base = f"{self._DIAS[dia.weekday()]} {dia.day} {self._MESES[dia.month - 1]}"
        if dia == hoy:
            return f"Hoy · {base}"
        if dia == hoy - pd.Timedelta(days=1):
            return f"Ayer · {base}"
        return (base.capitalize() + (f" {dia.year}" if dia.year != hoy.year else ""))

    def _dividir_por_dia(self, df):
        """[(dia, df_del_dia)] del más reciente al más antiguo; las filas sin
        fecha válida van al final."""
        col_fecha = self._col(df, 'FECHA')
        if df.empty or col_fecha is None:
            return [(None, df)] if not df.empty else []
        fechas = _a_fecha(df[col_fecha].astype(str).str.strip(), '%d-%m-%Y %H:%M:%S', dayfirst=True)
        dias = fechas.dt.normalize()
        # Un solo agrupamiento: una máscara por día recorría todo el log cada vez
        bloques = [(pd.Timestamp(dia), sub) for dia, sub in reversed(list(df.groupby(dias.values)))]
        if dias.isna().any():
            bloques.append((None, df[dias.isna().values]))
        return bloques

    _CAMPOS_MONTO = ("MONTO", "VALOR PLAN", "VAR", "DYNAFLEET", "VALOR", "PRECIO")

    @classmethod
    def _formato_valor(cls, campo, valor):
        """Montos con separador de miles y sin decimales de coma flotante
        (8396.178666 -> 8.396,18); el resto se muestra tal cual."""
        texto = str(valor).strip()
        try:
            numero = float(texto.replace(",", "."))
        except ValueError:
            return texto
        es_monto = any(k in str(campo).upper() for k in cls._CAMPOS_MONTO)
        largo_decimal = "." in texto and len(texto.split(".")[-1]) > 2
        if not (es_monto or largo_decimal):
            return texto
        entero = abs(numero - round(numero)) < 0.005
        formato = f"{numero:,.0f}" if entero else f"{numero:,.2f}"
        return formato.replace(",", "_").replace(".", ",").replace("_", ".")

    @staticmethod
    def _hora(valor):
        partes = str(valor).strip().split(" ")
        return partes[1][:5] if len(partes) > 1 else ""

    def _pintar(self):
        if self.tabs.currentIndex() == 2:
            self._pintar_conflictos()
        elif self.tabs.currentIndex() == 0:
            self._dias_mods = self._dividir_por_dia(self.filtered_mods)
            self._tanda_mods = self.DIAS_POR_TANDA
            self._pintar_mods()
        else:
            self._dias_del = self._dividir_por_dia(self.filtered_del)
            self._tanda_del = self.DIAS_POR_TANDA
            self._pintar_del()

    def _pintar_mods(self):
        lista = self.lista_mods
        lista.reiniciar()
        dias = self._dias_mods
        n_guardados = 0
        if not dias:
            lista.mostrar_vacio("No hay modificaciones en el rango elegido.")
        for i, (dia, df_dia) in enumerate(dias[:self._tanda_mods]):
            eventos = self._eventos_del_dia(df_dia)
            lista.agregar(self._bloque_dia(dia, eventos, len(df_dia), abierto=i < 2,
                                           constructor_eventos=self._cuerpo_eventos))
        n_guardados = self._contar_guardados(self.filtered_mods, dias)
        if len(dias) > self._tanda_mods:
            lista.boton_pie(f"Mostrar {min(self.DIAS_POR_TANDA, len(dias) - self._tanda_mods)} días más", self._mas_dias_mods)
        self._actualizar_resumen(n_guardados_mods=n_guardados)

    def _mas_dias_mods(self):
        self._tanda_mods += self.DIAS_POR_TANDA
        self._pintar_mods()

    def _contar_guardados(self, df, dias):
        """Total de _eventos_del_dia en todos los días sin agrupar día por
        día: cada fecha y hora cae en un solo día."""
        claves = [c for c in (self._col(df, 'FECHA'), self._col(df, 'MODULO', 'MÓDULO'), self._col(df, 'IDENTIFICADOR', 'VIN'))
                  if c is not None]
        if not claves:
            return len(dias)
        return len(df[claves].dropna().drop_duplicates())

    def _eventos_del_dia(self, df_dia):
        """[(fecha_hora, módulo, identificador, df_cambios)] en el orden del log."""
        col_f, col_m, col_i = self._col(df_dia, 'FECHA'), self._col(df_dia, 'MODULO', 'MÓDULO'), self._col(df_dia, 'IDENTIFICADOR', 'VIN')
        claves = [c for c in (col_f, col_m, col_i) if c is not None]
        if not claves:
            return [("", "", "", df_dia)]
        # Un guardado por combinación de las claves, en orden de aparición. Se numeran los grupos
        # y se parte por posiciones: iterar groupby armaba un DataFrame por guardado (más de mil por día)
        codigos = df_dia.groupby(claves, sort=False).ngroup().to_numpy(dtype=float)
        validos = np.flatnonzero(~np.isnan(codigos) & (codigos >= 0))
        if not len(validos):
            return []
        cod = codigos[validos].astype(np.int64)
        orden = np.argsort(cod, kind="stable")
        grupos = np.split(validos[orden], np.flatnonzero(np.diff(cod[orden])) + 1)
        primera = df_dia[claves[0]].to_numpy()
        modulo = df_dia[col_m].to_numpy() if col_m else None
        ident = df_dia[col_i].to_numpy() if col_i else None
        return [(primera[g[0]], str(modulo[g[0]]) if col_m else "", str(ident[g[0]]) if col_i else "", _Cambios(df_dia, g))
                for g in grupos]

    def _bloque_dia(self, dia, eventos, n_cambios, abierto, constructor_eventos):
        titulo = self._etiqueta_dia(dia) if dia is not None else "Sin fecha"
        bloque = admin_listas.Colapsable(constructor=lambda: constructor_eventos(eventos), abierto=abierto, nivel=1)
        bloque.agregar(admin_listas.texto(titulo, tam=14, negrita=True), 1)
        bloque.agregar(admin_listas.pildora(admin_listas.plural(len(eventos), "guardado"), "gris"))
        bloque.agregar(admin_listas.pildora(admin_listas.plural(n_cambios, "cambio"), "azul"))
        return bloque

    def _cuerpo_eventos(self, eventos):
        cuerpo = QWidget()
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        estado = {'n': 0, 'boton': None}

        def _agregar_tanda():
            if estado['boton'] is not None:
                lay.removeWidget(estado['boton'])
                estado['boton'].deleteLater()
                estado['boton'] = None
            for evento in eventos[estado['n']:estado['n'] + self.EVENTOS_POR_TANDA]:
                lay.addWidget(self._fila_evento(*evento))
            estado['n'] = min(len(eventos), estado['n'] + self.EVENTOS_POR_TANDA)
            if estado['n'] < len(eventos):
                boton = QPushButton(f"Mostrar {min(self.EVENTOS_POR_TANDA, len(eventos) - estado['n'])} guardados más")
                boton.setCursor(Qt.CursorShape.PointingHandCursor)
                boton.setStyleSheet(f"QPushButton {{ border: none; border-top: 1px solid {estilo_com.LINEA_SUAVE}; padding: 9px; "
                                    f"color: {estilo_com.AZUL}; font-weight: 700; background: transparent; }}")
                boton.clicked.connect(_agregar_tanda)
                lay.addWidget(boton)
                estado['boton'] = boton

        _agregar_tanda()
        return cuerpo

    def _fila_evento(self, fecha_hora, modulo, identificador, df_cambios):
        perezoso = isinstance(df_cambios, _Cambios)
        base = df_cambios.base if perezoso else df_cambios
        col_c = self._col(base, 'CAMPO')
        col_a = self._col(base, 'ANTERIOR')
        col_n = self._col(base, 'NUEVO')
        n = len(df_cambios)
        fila = admin_listas.Colapsable(
            constructor=lambda: self._detalle_cambios(df_cambios.filas if perezoso else df_cambios, col_c, col_a, col_n), nivel=2)
        hora = admin_listas.texto(self._hora(fecha_hora), color=estilo_com.APAGADO, tam=12)
        hora.setFixedWidth(44)
        fila.agregar(hora)
        if modulo:
            fila.agregar(admin_listas.pildora(modulo, self._TONOS_MODULO.get(str(modulo).upper(), "gris")))
        fila.agregar(admin_listas.texto(identificador or "-", tam=12, negrita=True), 1)
        fila.agregar(admin_listas.texto(admin_listas.plural(n, "campo"), color=estilo_com.APAGADO, tam=11))
        fila.hacer_copiable(identificador)
        return fila

    def _detalle_cambios(self, df, col_c, col_a, col_n):
        marco = QFrame()
        marco.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QGridLayout(marco)
        lay.setContentsMargins(52, 0, 16, 8)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(1)
        lay.setColumnMinimumWidth(0, 150)
        lay.setColumnStretch(1, 1)
        for r, (_, fila) in enumerate(df.iterrows()):
            if col_c is None:
                lay.addWidget(admin_listas.texto(" · ".join(f"{k}: {v}" for k, v in fila.items()), seleccionable=True), r, 0, 1, 2)
                continue
            lay.addWidget(admin_listas.texto(fila[col_c], color=estilo_com.APAGADO, tam=12), r, 0)
            antes = html.escape(self._formato_valor(fila[col_c], fila[col_a])) if col_a else ""
            despues = html.escape(self._formato_valor(fila[col_c], fila[col_n])) if col_n else ""
            lbl = QLabel(f'<span style="color:{estilo_com.ROJO}"><s>{antes}</s></span> '
                         f'<span style="color:{estilo_com.APAGADO}">→</span> '
                         f'<b style="color:{estilo_com.VERDE}">{despues}</b>')
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet("font-size: 12px; background: transparent; border: none;")
            lay.addWidget(lbl, r, 1)
        return marco

    # ---- Papelera: una fila por registro eliminado, con todas sus columnas
    def _pintar_del(self):
        lista = self.lista_del
        lista.reiniciar()
        dias = self._dias_del
        if not dias:
            lista.mostrar_vacio("No hay registros eliminados en el rango elegido.")
        for i, (dia, df_dia) in enumerate(dias[:self._tanda_del]):
            col_f = self._col(df_dia, 'FECHA')
            col_id = self._col(df_dia, 'VIN') or next((c for c in df_dia.columns if c != col_f), None)
            registros = [(str(f[col_f]) if col_f else "", self.combo_papelera_modulo.currentText(),
                          str(f[col_id]) if col_id else "", f) for _, f in df_dia.iterrows()]
            lista.agregar(self._bloque_dia(dia, registros, len(df_dia), abierto=i < 2,
                                           constructor_eventos=self._cuerpo_registros))
        if len(dias) > self._tanda_del:
            lista.boton_pie(f"Mostrar {min(self.DIAS_POR_TANDA, len(dias) - self._tanda_del)} días más", self._mas_dias_del)
        self._actualizar_resumen()

    def _mas_dias_del(self):
        self._tanda_del += self.DIAS_POR_TANDA
        self._pintar_del()

    def _cuerpo_registros(self, registros):
        cuerpo = QWidget()
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for fecha_hora, modulo, ident, fila in registros[:self.EVENTOS_POR_TANDA]:
            item = admin_listas.Colapsable(constructor=lambda f=fila: self._detalle_registro(f), nivel=2)
            hora = admin_listas.texto(self._hora(fecha_hora), color=estilo_com.APAGADO, tam=12)
            hora.setFixedWidth(44)
            item.agregar(hora)
            item.agregar(admin_listas.pildora(modulo, "rojo"))
            item.agregar(admin_listas.texto(ident or "-", tam=12, negrita=True), 1)
            item.hacer_copiable(ident)
            lay.addWidget(item)
        if len(registros) > self.EVENTOS_POR_TANDA:
            lay.addWidget(admin_listas.texto(
                f"Se muestran {self.EVENTOS_POR_TANDA} de {len(registros)}. Acota el rango para ver el resto.",
                color=estilo_com.APAGADO, tam=11))
        return cuerpo

    def _detalle_registro(self, fila):
        marco = QFrame()
        marco.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QGridLayout(marco)
        lay.setContentsMargins(52, 0, 16, 8)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(1)
        lay.setColumnMinimumWidth(0, 150)
        lay.setColumnStretch(1, 1)
        for r, (campo, valor) in enumerate(fila.items()):
            lay.addWidget(admin_listas.texto(campo, color=estilo_com.APAGADO, tam=12), r, 0)
            lay.addWidget(admin_listas.texto(valor if str(valor).strip() else "-", tam=12, seleccionable=True), r, 1)
        return marco

