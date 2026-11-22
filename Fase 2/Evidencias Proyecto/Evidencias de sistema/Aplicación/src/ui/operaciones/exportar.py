"""Exportaciones de Excel de la cola de Operaciones."""
import os
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import QMessageBox, QFileDialog
from PyQt6.QtCore import QStandardPaths
from src.core.constants import COL_CDB_FLOTA
from src.services import operaciones_services
from src.ui.operaciones.base import (
    IDX_ACTIVACIONES,
    IDX_CONTACTOS,
)


class _ExportarOperacionesMixin:
    # ---------------------------------------------------------------
    # BOTÓN "Exportar contactos" -- pedido de Javiera: darle al ejecutivo
    # los datos de contacto de los clientes de Activaciones. Se resuelve
    # como un Excel descargable (no hay definición de a quién/cómo
    # entregarlo automáticamente), cruzando por CDB contra Contactos.xlsx
    # -- misma fuente que usa src/ui/contactos.py, no un archivo nuevo.
    # ---------------------------------------------------------------
    def _exportar_cdb_sin_contacto(self):
        """En "Contactos": los CDB sin administrador de flota (los seleccionados o todos los de la lista),
        con su flota y el ejecutivo que los lleva."""
        full = self._cola_full.get(IDX_CONTACTOS, pd.DataFrame())
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        visible = self.model.get_df()
        if filas and COL_CDB_FLOTA in visible.columns:
            cdbs = set(visible.iloc[filas][COL_CDB_FLOTA].astype(str).str.strip())
            full = full[full[COL_CDB_FLOTA].astype(str).str.strip().isin(cdbs)]
        df_resultado = operaciones_services.armar_export_cdb_sin_contacto(full, self.df_master)
        if df_resultado.empty:
            QMessageBox.information(self, "Exportar contactos", "No hay CDB para exportar.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", "CDB_sin_administrador_de_flota.xlsx", "Archivos Excel (*.xlsx)")
        if not filepath:
            return
        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, df_resultado, filepath, atributo_hilo='_export_contactos_thread',
                            titulo="CDB sin administrador de flota")

    def _on_exportar_contactos_clicked(self):
        idx = self.subtabs.currentIndex()
        if idx == IDX_CONTACTOS:
            self._exportar_cdb_sin_contacto()
            return
        full = self._cola_full.get(idx, pd.DataFrame())
        if full.empty:
            return
        pestana = self.subtabs.tabText(idx).split()[0].capitalize()

        vins = self._get_selected_vins()
        if vins:
            vins_upper = {v.strip().upper() for v in vins}
            df_base = full[full['VIN'].astype(str).str.strip().str.upper().isin(vins_upper)]
        else:
            df_base = full

        if df_base.empty:
            QMessageBox.information(self, "Exportar contactos", "No hay unidades para exportar.")
            return

        df_contactos = self.data_manager.get_contactos_df()
        df_resultado = operaciones_services.armar_export_contactos_ejecutivo(df_base, df_contactos)
        if df_resultado.empty:
            QMessageBox.information(self, "Exportar contactos", "No hay datos para exportar.")
            return
        if idx != IDX_ACTIVACIONES:
            df_resultado = df_resultado.rename(columns={'VINES PENDIENTES': 'VINES'})

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", f"Contactos_{pestana}.xlsx", "Archivos Excel (*.xlsx)"
        )
        if not filepath:
            return

        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, df_resultado, filepath, atributo_hilo='_export_contactos_thread',
                            titulo=f"Contactos {pestana}")

    # ---------------------------------------------------------------
    # BOTÓN "Exportar VIN & CDB" (29-09-2026, a pedido explícito): VIN y CDB
    # de la tabla visible (con ediciones en celda incluidas; solo las filas
    # seleccionadas si hay alguna), guardado directo en el Escritorio.
    # ---------------------------------------------------------------
    def _on_exportar_vin_cdb_clicked(self):
        df_visible = self.model.get_df()
        columnas = [c for c in ('VIN', 'CDB FLOTA', 'TIPO DE SERVICIO') if c in df_visible.columns]
        if df_visible.empty or not columnas:
            QMessageBox.information(self, "Exportar VIN & CDB", "No hay unidades para exportar.")
            return

        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        df_export = df_visible.iloc[filas] if filas else df_visible
        df_export = df_export[columnas].rename(columns={'TIPO DE SERVICIO': 'PLAN'})
        columnas = list(df_export.columns)

        pestana = self.subtabs.tabText(self.subtabs.currentIndex()).strip().replace(" ", "_")
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        base = os.path.join(carpeta, f"VIN_CDB_{pestana}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}")
        filepath, n = f"{base}.xlsx", 2
        while os.path.exists(filepath):
            filepath, n = f"{base}_{n}.xlsx", n + 1

        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, df_export.astype(str).reset_index(drop=True), filepath,
                            atributo_hilo='_export_vin_cdb_thread', con_resumen=False, hoja="VIN y CDB")
