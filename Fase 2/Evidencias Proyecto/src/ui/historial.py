import csv
import html
import os

import pandas as pd
from datetime import datetime
import qtawesome as qta
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel, QFrame,
                             QPushButton, QMessageBox, QLineEdit, QTabWidget)
from PyQt6.QtCore import Qt
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.perf_log import medir
from src.ui import admin_estilo, admin_listas, comercial_estilo as estilo_com
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
import openpyxl
import config.settings

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
        
        self._setup_ui()
        self.load_data()

    def _setup_ui(self):
        main_layout = admin_estilo.raiz_pantalla(self)

        contenedor_tabs, self.subtabs, self._badges = admin_estilo.subpestanas(("Logs de modificaciones", "Papelera"))
        main_layout.addWidget(contenedor_tabs)
        admin_estilo.animar_subpestanas(self, self.subtabs)

        self._barra = admin_estilo.barra_opciones('fa5s.history', "Historial de cambios", "")
        main_layout.addWidget(self._barra.marco)

        # Rango de tiempo y, solo en la Papelera, el módulo de origen:
        # RegistroEliminado.xlsx guarda una hoja por módulo, cada una con su
        # propio esquema de columnas, y no se mezclan.
        self.cb_rango_fechas = estilo_com.ComboTarjeta("Rango de tiempo")
        self.cb_rango_fechas.addItems(["Todos los tiempos", "Hoy", "Últimos 7 días", "Últimos 30 días", "Último Año"])
        self.cb_rango_fechas.currentTextChanged.connect(lambda: self.filter_tables(reset_page=True))
        admin_estilo.combo_barra(self.cb_rango_fechas, 170)

        self.lbl_papelera_modulo = admin_estilo.etiqueta_barra("Módulo eliminado")
        self.combo_papelera_modulo = estilo_com.ComboTarjeta("Módulo eliminado")
        self.combo_papelera_modulo.currentTextChanged.connect(lambda: self.filter_tables(reset_page=True))
        admin_estilo.combo_barra(self.combo_papelera_modulo, 170)

        zona = self._barra.zona_filtros
        zona.addWidget(admin_estilo.etiqueta_barra("Rango"))
        zona.addWidget(self.cb_rango_fechas)
        zona.addSpacing(8)
        zona.addWidget(self.lbl_papelera_modulo)
        zona.addWidget(self.combo_papelera_modulo)

        # Vacía la pestaña activa (LogApp.csv o RegistroEliminado.xlsx) con
        # backup previo y conservando encabezados (ver _clear_logs).
        self.btn_clear = admin_estilo.boton_capsula(self._barra, 'fa5s.trash-alt', "Vaciar pestaña actual", QPushButton())
        self.btn_clear.clicked.connect(self._clear_logs)
        self.btn_export_excel = admin_estilo.boton_capsula(self._barra, 'fa5s.file-excel', "Exportar a Excel", QPushButton())
        self.btn_export_excel.clicked.connect(self._export_current_tab_excel)
        self.btn_reload = admin_estilo.boton_capsula(self._barra, 'fa5s.sync-alt', "Actualizar", QPushButton())
        self.btn_reload.clicked.connect(self.data_manager.load_data_async)

        marco, capas = admin_estilo.tarjeta_contenido("tarjetaHistorial")
        self.tabs = QTabWidget()

        self.lista_mods = admin_listas.ListaAgrupada()
        self.tabs.addTab(self.lista_mods, "Logs de Modificaciones")
        self.lista_del = admin_listas.ListaAgrupada()
        self.tabs.addTab(self.lista_del, "Papelera (Registros Eliminados)")

        admin_estilo.enlazar_tabs(self.subtabs, self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        capas.addWidget(self.tabs, 1)

        main_layout.addWidget(marco, 1)
        self._on_tab_changed()

    def _actualizar_resumen(self, n_guardados_mods=0, n_guardados_del=0):
        """Contadores de las sub-pestañas y subtítulo según los filtros vigentes."""
        n_m, n_d = len(self.filtered_mods), len(self.filtered_del)
        admin_estilo.actualizar_contador(self.subtabs, self._badges, 0, n_m)
        admin_estilo.actualizar_contador(self.subtabs, self._badges, 1, n_d)
        rango = self.cb_rango_fechas.currentText().lower()
        if self.tabs.currentIndex() == 0:
            self._barra.lbl_subtitulo.setText(f"{n_m} cambios en {n_guardados_mods} guardados · {rango}")
        else:
            self._barra.lbl_subtitulo.setText(f"{n_d} registros eliminados · {rango}")

    def _on_tab_changed(self):
        es_papelera = self.tabs.currentIndex() == 1
        self.lbl_papelera_modulo.setVisible(es_papelera)
        self.combo_papelera_modulo.setVisible(es_papelera)

        # Ambas pestañas vacían con backup previo y conservan los encabezados.
        self.btn_clear.setEnabled(True)
        if es_papelera:
            self.btn_clear.setToolTip("Elimina todos los registros de todas las hojas de la Papelera, con backup previo.")
        else:
            self.btn_clear.setToolTip("Elimina todos los registros del historial de modificaciones, con backup previo.")

        self._pintar()

    # =========================================================
    # FUNCIÓN PARA ELIMINAR EL ARCHIVO EXCEL GIGANTE
    # =========================================================
    def _clear_logs(self):
        is_mods = self.tabs.currentIndex() == 0

        if is_mods:
            self._clear_logs_modificaciones()
            return

        self._clear_papelera()

    def _clear_logs_modificaciones(self):
        # Vacía LogApp.csv dejando solo la línea de encabezado, con backup previo.
        msg = QMessageBox(self)
        msg.setWindowTitle("Vaciar Logs de Modificaciones")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "¿Estás seguro de que deseas eliminar TODOS los registros del historial de modificaciones?\n\n"
            "Esta acción borrará todas las filas de datos, manteniendo los encabezados intactos."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        filepath = config.settings.LOG_CSV_PATH
        if not filepath or not os.path.exists(filepath):
            QMessageBox.information(self, "Aviso", "El historial de modificaciones no existe o ya está vacío.")
            return

        if not self.writer._crear_backup(filepath):
            QMessageBox.warning(
                self, "Error",
                "No se pudo crear el backup de LogApp.csv antes de vaciarlo. "
                "Por seguridad, no se eliminó ningún registro. Inténtalo nuevamente."
            )
            return

        try:
            with open(filepath, 'r', encoding='utf-8-sig', newline='') as f:
                encabezado = f.readline()
                filas_borradas = sum(1 for fila in csv.reader(f) if any(fila))
            if not encabezado.strip():
                QMessageBox.information(self, "Aviso", "El historial de modificaciones ya está vacío.")
                return
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(encabezado if encabezado.endswith(('\n', '\r')) else encabezado + '\r\n')
        except PermissionError:
            QMessageBox.warning(self, "Error", "El archivo está abierto o bloqueado. Ciérralo e inténtalo de nuevo.")
            return
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Ocurrió un problema: {e}")
            return

        if filas_borradas == 0:
            QMessageBox.information(self, "Aviso", "El historial de modificaciones ya estaba vacío.")
        else:
            QMessageBox.information(
                self, "Éxito",
                f"Se eliminaron {filas_borradas} registro(s) del historial, manteniendo los encabezados."
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
        msg.setWindowTitle("Vaciar Papelera")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "¿Estás seguro de que deseas eliminar TODOS los registros de la Papelera, "
            "en todos los módulos (Comercial, Provisiones, Contactos, etc.)?\n\n"
            "Esta acción borrará todas las filas de datos de cada hoja, manteniendo "
            "los encabezados y la estructura de hojas intactos."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        filepath = config.settings.DELETED_LOG_EXCEL_PATH
        if not filepath or not os.path.exists(filepath):
            QMessageBox.information(self, "Aviso", "El archivo de la Papelera no existe o ya está vacío.")
            return

        if not self.writer._crear_backup(filepath):
            QMessageBox.warning(
                self, "Error",
                "No se pudo crear el backup de RegistroEliminado.xlsx antes de vaciar la Papelera. "
                "Por seguridad, no se eliminó ningún registro. Inténtalo nuevamente."
            )
            return

        try:
            # Instrumentacion temporal (auditoria de rendimiento B-3,
            # 18-09-2026): separa la carga del workbook, el borrado de filas
            # por hoja y el guardado final, todo en Main Thread. No cambia
            # el comportamiento.
            with medir("B-3 _clear_papelera > load_workbook"):
                wb = openpyxl.load_workbook(filepath)
            total_hojas = len(wb.sheetnames)
            hojas_con_datos = 0
            filas_totales_borradas = 0
            with medir(f"B-3 _clear_papelera > delete_rows ({total_hojas} hojas)"):
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    if ws.max_row > 1:
                        filas_totales_borradas += ws.max_row - 1
                        ws.delete_rows(2, ws.max_row - 1)
                        hojas_con_datos += 1
            with medir("B-3 _clear_papelera > wb.save"):
                wb.save(filepath)
            wb.close()
            print(f"[PERF][UI] B-3 _clear_papelera -> {filas_totales_borradas} filas borradas en {hojas_con_datos} hojas")
        except PermissionError:
            QMessageBox.warning(self, "Error", "El archivo está abierto en Excel o bloqueado. Ciérralo e inténtalo de nuevo.")
            return
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Ocurrió un problema: {e}")
            return

        if hojas_con_datos == 0:
            QMessageBox.information(self, "Aviso", f"La Papelera ya estaba vacía ({total_hojas} hoja(s), sin registros).")
        else:
            QMessageBox.information(
                self, "Éxito",
                f"Se han limpiado los registros de {hojas_con_datos} de {total_hojas} hoja(s) de la Papelera, "
                "manteniendo los encabezados y todas las hojas."
            )
        self.data_manager.load_data_async()  # Recargamos la interfaz


    def _export_current_tab_excel(self):
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

    def load_data(self):
        self._data_dirty = False
        self.df_mods_base = self.data_manager.get_logs_df()
        # deleted_sheets_base: {nombre_modulo: DataFrame}, una por hoja de
        # RegistroEliminado.xlsx (ver DataManager.get_deleted_logs_sheets). Se
        # mantiene cada hoja separada con su propio esquema; no se fusionan
        # columnas de distintos módulos en una sola tabla.
        self.deleted_sheets_base = self.data_manager.get_deleted_logs_sheets()

        # --- TRADUCTOR AL FORMATO LATINO (DD-MM-YYYY HH:MM:SS) ---
        def formatear_fechas(df):
            if df.empty: return df
            col_fecha = next((c for c in df.columns if 'FECHA' in str(c).upper() or 'FECHAHORA' in str(c).upper()), None)
            if col_fecha:
                try:
                    df[col_fecha] = pd.to_datetime(df[col_fecha], format='mixed', errors='coerce').dt.strftime('%d-%m-%Y %H:%M:%S').fillna(df[col_fecha])
                except: pass
            return df

        self.df_mods_base = formatear_fechas(self.df_mods_base)
        if not self.df_mods_base.empty: self.df_mods_base = self.df_mods_base.iloc[::-1].reset_index(drop=True)

        for nombre_modulo, df_hoja in self.deleted_sheets_base.items():
            df_hoja = formatear_fechas(df_hoja)
            if not df_hoja.empty: df_hoja = df_hoja.iloc[::-1].reset_index(drop=True)
            self.deleted_sheets_base[nombre_modulo] = df_hoja

        self._actualizar_combo_papelera_modulo()
        self.filter_tables(reset_page=True)

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
            if df.empty or col_fecha not in df.columns:
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
        fechas = pd.to_datetime(df[col_fecha].astype(str).str.strip(), dayfirst=True, format='mixed', errors='coerce')
        dias = fechas.dt.normalize()
        bloques = []
        for dia in sorted(dias.dropna().unique(), reverse=True):
            bloques.append((pd.Timestamp(dia), df[(dias == dia).values]))
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
        if self.tabs.currentIndex() == 0:
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
        n_guardados = sum(len(self._eventos_del_dia(d)) for _, d in dias)
        if len(dias) > self._tanda_mods:
            lista.boton_pie(f"Mostrar {min(self.DIAS_POR_TANDA, len(dias) - self._tanda_mods)} días más", self._mas_dias_mods)
        self._actualizar_resumen(n_guardados_mods=n_guardados)

    def _mas_dias_mods(self):
        self._tanda_mods += self.DIAS_POR_TANDA
        self._pintar_mods()

    def _eventos_del_dia(self, df_dia):
        """[(fecha_hora, módulo, identificador, df_cambios)] en el orden del log."""
        col_f, col_m, col_i = self._col(df_dia, 'FECHA'), self._col(df_dia, 'MODULO', 'MÓDULO'), self._col(df_dia, 'IDENTIFICADOR')
        claves = [c for c in (col_f, col_m, col_i) if c is not None]
        if not claves:
            return [("", "", "", df_dia)]
        return [(k[0] if isinstance(k, tuple) else k, str(g[col_m].iloc[0]) if col_m else "",
                 str(g[col_i].iloc[0]) if col_i else "", g)
                for k, g in df_dia.groupby(claves, sort=False)]

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
        col_c = self._col(df_cambios, 'CAMPO')
        col_a = self._col(df_cambios, 'ANTERIOR')
        col_n = self._col(df_cambios, 'NUEVO')
        n = len(df_cambios)
        fila = admin_listas.Colapsable(constructor=lambda: self._detalle_cambios(df_cambios, col_c, col_a, col_n), nivel=2)
        hora = admin_listas.texto(self._hora(fecha_hora), color=estilo_com.APAGADO, tam=12)
        hora.setFixedWidth(44)
        fila.agregar(hora)
        if modulo:
            fila.agregar(admin_listas.pildora(modulo, self._TONOS_MODULO.get(str(modulo).upper(), "gris")))
        fila.agregar(admin_listas.texto(identificador or "-", tam=12, negrita=True), 1)
        fila.agregar(admin_listas.texto(admin_listas.plural(n, "campo"), color=estilo_com.APAGADO, tam=11))
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
