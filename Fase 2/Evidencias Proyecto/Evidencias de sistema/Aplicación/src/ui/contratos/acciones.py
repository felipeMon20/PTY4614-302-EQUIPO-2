"""Acciones rápidas de Contratos (CM): pasar a CM, limpiar, estado por pago, extender y avisar."""
from src.theme.colors import PRIMARY
import pandas as pd
from PyQt6.QtWidgets import QMessageBox, QDialog
import config.settings
from src.ui.compartido.custom_table import ExportExcelThread
from src.services import cm_bajas_service
from src.services import comercial_services
from src.services import contratos_service as ct_service
from src.core.dataframe_formatter import DataFrameFormatter
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.core.constants import COL_ESTADO_COMERCIAL, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO, VALOR_ESTADO_COMERCIAL_BAJA, COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, COL_RUT, COL_RAZON_SOCIAL, COL_ESTADO_ACTIVACION, COL_CDB_FLOTA
from src.ui.contratos.base import logger, _ETIQUETA_SITUACION_PAGO, _FilasPorVin
from src.ui.contratos.dialogos import ResumenPasarACM, ExtenderDuracionDialog
from src.ui.contratos.base import (
    _ETIQUETA_SITUACION_PAGO,
    _FilasPorVin,
    logger,
)
from src.ui.contratos.dialogos import (
    ExtenderDuracionDialog,
    ResumenPasarACM,
)


class _AccionesContratosMixin:
    # --------------------------------------------- acciones rápidas del panel
    def _vins_running_terminados(self):
        """VIN seleccionados con el CM en Running, término vencido y sin pago este mes."""
        base = self._base_por_vin()
        vins = []
        for vin in (v.upper() for v in self._vins_seleccionados()):
            fila = base.get(vin)
            if fila is not None and ct_service.es_running_terminado_sin_pago(fila):
                vins.append(vin)
        return vins

    def _on_marcar_expired_clicked(self):
        vins = self._vins_running_terminados()
        if not vins:
            return
        base = self._base_por_vin()
        valid = {}
        for vin in vins:
            fila = base.get(vin, {})
            etapa = self._etapa_nueva(fila, 'Vencido', fila.get(COL_TIPO_FACTURACION, ''))
            valid[vin] = {'VIN': vin, 'cambios': {'ESTADO DEL CM': 'Expired', COL_ESTADO_COMERCIAL: 'Vencido', COL_ETAPA_GESTION: etapa}}
        self._guardar_accion_rapida(valid, "Marcando los contratos como Expired y Vencido…")

    def _base_por_vin(self):
        base = self.data_manager.get_contratos_actuales_df()
        if base is None or base.empty or 'VIN' not in base.columns:
            return {}
        base = base.drop_duplicates('VIN', keep='last')
        return _FilasPorVin(base.set_index(base['VIN'].astype(str).str.strip().str.upper()))

    @staticmethod
    def _etapa_nueva(fila, estado_comercial, tipo_facturacion):
        return DataFrameFormatter.calcular_etapa_gestion_esperada({
            COL_ESTADO_COMERCIAL: estado_comercial,
            COL_ESTADO_ACTIVACION: fila.get(COL_ESTADO_ACTIVACION, ''),
            COL_TIPO_FACTURACION: tipo_facturacion,
            COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
        })

    def _cambios_pasar_a_cm(self, vins=None):
        """{VIN: cambios} de los contratos (por defecto los seleccionados) cuya forma no es CM."""
        base = self._base_por_vin()
        cambios = {}
        for vin in (v.upper() for v in (self._vins_seleccionados() if vins is None else vins)):
            if vin not in self._vins_forma_no_cm:
                continue
            fila = base.get(vin, {})
            nuevo = ct_service.cambio_opcional_a_cm(fila.get('TIPO DE CM', ''), fila.get(COL_FORMA_CONTRATO, ''))
            if nuevo:
                cambios[vin] = nuevo
        return cambios

    def _confirmar_accion_rapida(self, titulo, icono, subtitulo, descripcion, lineas=None):
        dialogo = DialogoAccion(
            self, f" {titulo}", icon_name=icono, icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo=titulo, subtitulo=subtitulo, descripcion=descripcion, items=lineas,
            titulo_items="Cambios",
            botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                     {'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}])
        return dialogo.exec() == QDialog.DialogCode.Accepted

    def _guardar_accion_rapida(self, valid, texto, contratos_nuevos=None):
        comercial_services.agregar_id_a_cambios(valid, self.data_manager.get_contratos_actuales_df())
        self.pending_changes.update(valid)
        self._contratos_nuevos_pendientes = list(contratos_nuevos or [])
        self._emitir_data_ready_tras_guardar = True
        self._iniciar_guardado(valid, texto, self._contratos_nuevos_pendientes)

    def _on_enviar_operaciones_clicked(self):
        vins = [v.upper() for v in self._vins_seleccionados()]
        if not vins:
            return
        base = self._base_por_vin()
        valid = {}
        for vin in vins:
            fila = base.get(vin, {})
            etapa = self._etapa_nueva(fila, VALOR_ESTADO_COMERCIAL_BAJA, fila.get(COL_TIPO_FACTURACION, ''))
            valid[vin] = {'VIN': vin, 'cambios': {COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_BAJA, COL_ETAPA_GESTION: etapa}}
        self._guardar_accion_rapida(valid, "Enviando a Operaciones…")

    def _cambios_limpiar_cm(self):
        """{VIN: cambios} de los contratos seleccionados que ya no son CM y aún traen datos de CM."""
        base = self.data_manager.get_contratos_actuales_df()
        if base is None or base.empty or 'VIN' not in base.columns:
            return {}
        vins = {v.upper() for v in self._vins_seleccionados()}
        seleccion = base[base['VIN'].astype(str).str.strip().str.upper().isin(vins)]
        return ct_service.construir_cambios_limpieza_cm(seleccion)

    def _on_limpiar_cm_clicked(self):
        cambios = self._cambios_limpiar_cm()
        if not cambios:
            return
        detalle = [f"{len(cambios)} contrato(s) quedan sin N° de contrato 3PC, fechas, tipo, estado ni pago del CM",
                   "El último pago y su fecha se conservan",
                   "El cambio queda en el historial"]
        if not self._confirmar_accion_rapida(
                "Limpiar datos CM", 'fa5s.eraser', f"{len(cambios)} contrato(s) dejan de ser CM",
                "Su forma de contrato y su facturación no son de CM, pero aún traen datos antiguos del 3PC. "
                "Mientras el 3PC los siga listando como vencidos, la importación no los vuelve a cargar.", detalle):
            return
        self._guardar_accion_rapida(cambios, "Limpiando los datos del CM…")

    def _on_pasar_a_cm_clicked(self):
        self._pasar_a_cm(self._cambios_pasar_a_cm())

    def _on_pasar_a_cm_todos_clicked(self):
        self._pasar_a_cm(self._cambios_pasar_a_cm(self._vins_visibles))

    def _pasar_a_cm(self, cambios_por_vin):
        if not cambios_por_vin:
            return
        base = self._base_por_vin()
        siguiente_id = comercial_services.proximo_id_contrato(self.data_manager.df_master)
        vins_provision = {vin for vin in cambios_por_vin
                          if siguiente_id and ct_service.es_forma_provision(base.get(vin, {}).get(COL_FORMA_CONTRATO, ''))}
        filas = []
        for vin, nuevo in cambios_por_vin.items():
            fila = base.get(vin, {})
            filas.append({
                'vin': vin,
                'forma_antes': str(fila.get(COL_FORMA_CONTRATO, '-')).strip() or '-', 'forma_ahora': nuevo[COL_FORMA_CONTRATO],
                'fact_antes': str(fila.get(COL_TIPO_FACTURACION, '-')).strip() or '-', 'fact_ahora': nuevo[COL_TIPO_FACTURACION],
                'contrato_nuevo': vin in vins_provision})
        if ResumenPasarACM(self, filas).exec() != QDialog.DialogCode.Accepted:
            return
        valid = {}
        contratos_nuevos = []
        for vin, nuevo in cambios_por_vin.items():
            fila = base.get(vin, {})
            if vin in vins_provision:
                anterior, registro = ct_service.construir_renovacion_provision_a_cm(fila, nuevo, siguiente_id)
                siguiente_id = str(int(siguiente_id) + 1)
                valid[vin] = {'VIN': vin, 'cambios': anterior}
                contratos_nuevos.append(registro)
                continue
            cambios = dict(nuevo)
            etapa = self._etapa_nueva(fila, fila.get(COL_ESTADO_COMERCIAL, ''), nuevo[COL_TIPO_FACTURACION])
            if str(etapa).strip().upper() != str(fila.get(COL_ETAPA_GESTION, '')).strip().upper():
                cambios[COL_ETAPA_GESTION] = etapa
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        self._guardar_accion_rapida(valid, "Cambiando la forma de contrato…", contratos_nuevos)

    def _cambios_estado_por_pago(self, vins=None):
        """{VIN: 'Vigente' | 'Vencido'} de los contratos (por defecto los seleccionados) cuyo estado comercial
        cambia según el pago del mes (ver contratos_service.estado_comercial_por_pago)."""
        base = self._base_por_vin()
        cambios = {}
        for vin in (v.upper() for v in (self._vins_seleccionados() if vins is None else vins)):
            fila = base.get(vin)
            nuevo = ct_service.estado_comercial_por_pago(fila) if fila is not None else None
            if nuevo:
                cambios[vin] = nuevo
        return cambios

    def _on_actualizar_estado_clicked(self):
        self._actualizar_estado(self._cambios_estado_por_pago(), confirmar=False)

    def _on_actualizar_estado_todos_clicked(self):
        self._actualizar_estado(self._cambios_estado_por_pago(self._vins_visibles), confirmar=True)

    def _actualizar_estado(self, cambios_por_vin, confirmar):
        if not cambios_por_vin:
            return
        if confirmar:
            vigentes = sum(1 for e in cambios_por_vin.values() if e == "Vigente")
            vencidos = len(cambios_por_vin) - vigentes
            detalle = [f"{vigentes} contrato(s) pasan a Vigente (pagaron este mes y están conectados)"]
            if vencidos:
                detalle.append(f"{vencidos} contrato(s) pasan a Vencido (estaban en Revisar y no pagaron)")
            if not self._confirmar_accion_rapida(
                    "Actualizar estado", 'fa5s.check-double', f"{len(cambios_por_vin)} contrato(s) cambian de estado",
                    "El estado comercial se actualiza según el pago CM del mes y la etapa de gestión se recalcula sola.", detalle):
                return
        base = self._base_por_vin()
        valid = {}
        for vin, estado in cambios_por_vin.items():
            fila = base.get(vin, {})
            etapa = self._etapa_nueva(fila, estado, fila.get(COL_TIPO_FACTURACION, ''))
            valid[vin] = {'VIN': vin, 'cambios': {COL_ESTADO_COMERCIAL: estado, COL_ETAPA_GESTION: etapa}}
        self._guardar_accion_rapida(valid, "Actualizando el estado de los contratos…")

    def _filas_extensibles(self):
        """{VIN: fila} de los contratos seleccionados a los que se les puede sumar duración."""
        base = self._base_por_vin()
        filas = {}
        for vin in (v.upper() for v in self._vins_seleccionados()):
            fila = base.get(vin)
            if fila is not None and comercial_services.calcular_renovacion(fila, 1):
                filas[vin] = fila
        return filas

    def _on_extender_clicked(self):
        filas = self._filas_extensibles()
        if not filas:
            return
        dialogo = ExtenderDuracionDialog(self, filas)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        meses = dialogo.meses()
        valid = {}
        for vin, fila in filas.items():
            cambios = comercial_services.calcular_renovacion(fila, meses)
            if cambios.get(COL_ESTADO_COMERCIAL):
                cambios[COL_ESTADO_COMERCIAL] = cambios[COL_ESTADO_COMERCIAL].capitalize()
                cambios[COL_ETAPA_GESTION] = self._etapa_nueva(fila, cambios[COL_ESTADO_COMERCIAL], fila.get(COL_TIPO_FACTURACION, ''))
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        self._guardar_accion_rapida(valid, "Extendiendo la duración de los contratos…")

    def _exportar_detalle_excel(self):
        """Un contrato por fila con todos sus datos: en la fase 1 los de todas las flotas de la lista;
        dentro de una flota, los de esa flota."""
        df = self.model.get_df()
        if df is None or df.empty:
            QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
            return
        if self.empresa_actual is not None:
            df = df[df[COL_RAZON_SOCIAL] == self.empresa_actual]
        df = df.rename(columns={'SITUACION_PAGO': 'SITUACIÓN DE PAGO', COL_ULTIMO_PAGO_CM: 'PAGO DEL MES ANTERIOR',
                                'PAGO CM': 'PAGO CM ACTUAL'}).copy()
        df['SITUACIÓN DE PAGO'] = df['SITUACIÓN DE PAGO'].map(_ETIQUETA_SITUACION_PAGO).fillna(df['SITUACIÓN DE PAGO'])
        for col in ('PAGO DEL MES ANTERIOR', 'PAGO CM ACTUAL'):
            if col in df.columns:
                monto = ExportExcelThread._parsear_columna_numerica(df[col])
                df[col] = pd.to_numeric(monto, errors='coerce').fillna(0).astype(int)
        columnas = ['FLOTA VC', 'ESTADO DEL CM', 'PAGO DEL MES ANTERIOR', 'PAGO CM ACTUAL', COL_FECHA_ULTIMO_PAGO_CM,
                    'SITUACIÓN DE PAGO', COL_RAZON_SOCIAL, COL_RUT, COL_CDB_FLOTA, 'EJECUTIVO', 'VIN', 'CHASIS',
                    COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, 'TIPO DE SERVICIO',
                    'N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM']
        resaltado = ('SITUACIÓN DE PAGO', {
            _ETIQUETA_SITUACION_PAGO[ct_service.SITUACION_SIN_PAGO]: ("FDE2E1", "B91C1C"),
            _ETIQUETA_SITUACION_PAGO[ct_service.SITUACION_POR_ACTUALIZAR]: ("FFEFC2", "B45309")})
        # Con el módulo como widget, la tarjeta de avance se dibuja en la ventana visible (la tabla oculta no tiene)
        from src.ui.administracion.estilo import exportar_excel
        exportar_excel(self, df[[c for c in columnas if c in df.columns]].reset_index(drop=True), "Reporte_CM", resaltado=resaltado)

    def _on_avisar_clicked(self):
        """Correo de aviso de vencimiento por los contratos seleccionados."""
        from src.ui.compartido.mail_dialog import MailDialog
        from src.services import mail_service, mail_sync_service
        vins = [v.upper() for v in self._vins_seleccionados()]
        if not vins:
            return
        faltantes = mail_sync_service.vins_faltantes_en_correos(vins, config.settings.CORREOS_EXCEL_PATH)
        if faltantes:
            respuesta = QMessageBox.question(
                self, "Faltan correos",
                f"{len(faltantes)} de estos VIN no están en la base de correos. ¿Abrir el gestor de correos para sincronizarla?")
            if respuesta == QMessageBox.StandardButton.Yes:
                MailDialog(parent=self).exec()
            return
        MailDialog(parent=self, vins_preseleccionados=vins, plantilla_inicial=mail_service.PLANTILLA_AVISO_VENCIMIENTO).exec()

    def _on_confirmar_baja_clicked(self):
        vins = [v.upper() for v in self._vins_seleccionados() if v.upper() in self._vins_ausentes]
        if not vins:
            return
        if not self._confirmar_accion_rapida(
                "Confirmar baja", 'fa5s.check-circle', f"{len(vins)} contrato(s) pasan a Baja",
                "El CM queda en Terminated (conserva sus datos) y el contrato pasa a Baja para que Operaciones desconecte la unidad.", vins):
            return
        base = self._base_por_vin()
        valid = {}
        for vin in vins:
            fila = base.get(vin, {})
            etapa = self._etapa_nueva(fila, VALOR_ESTADO_COMERCIAL_BAJA, fila.get(COL_TIPO_FACTURACION, ''))
            valid[vin] = {'VIN': vin, 'cambios': {'ESTADO DEL CM': 'Terminated', COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_BAJA,
                                                   COL_ETAPA_GESTION: etapa}}
        try:
            casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
            pendientes = casos[(casos['ESTADO_CASO'] == cm_bajas_service.ESTADO_CASO_PENDIENTE)
                               & (casos['ORIGEN_CASO'] == cm_bajas_service.ORIGEN_CASO_AUSENCIA_3PC)
                               & (casos['VIN'].astype(str).str.strip().str.upper().isin(vins))]
            self._casos_a_cerrar = [c for c in pendientes['CASO_ID'] if str(c).strip()]
        except Exception as e:
            logger.error(f"No se pudieron leer los casos de baja CM: {e}")
            self._casos_a_cerrar = []
        self._guardar_accion_rapida(valid, "Confirmando la baja del CM…")

    def _on_editar_unidad_clicked(self):
        vins = self._vins_seleccionados()
        if len(vins) != 1:
            return
        fila = self._fila_por_vin.get(vins[0], {})
        self._abrir_form_contrato(int(fila.get('_ROW_IDX', 0)), fila)
