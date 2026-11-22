"""Armado de la bandeja Revisión CM de Comercial."""
import pandas as pd
from src.services import cm_bajas_service
from src.services import comercial_services
from src.services import contratos_service as ct_service
import config.settings


class _RevisionCmComercialMixin:
    def _construir_df_revision_cm(self):
        """Bandeja de "Revisión CM": casos PENDIENTE de CasosBajaCM.csv (ver
        cm_bajas_service.py), sin importar su ORIGEN_CASO -- incluye tanto
        VIN que tenían datos CM y dejaron de aparecer en el Excel mensual
        de 3PC (AUSENCIA_3PC) como VIN cuyo contrato pasó a ESTADO DEL CM =
        'Expired' (ESTADO_EXPIRED). No incluye REAPARECIDO (el caso ya se
        resolvió solo: el VIN reapareció en el 3PC, o el contrato dejó de
        estar Expired), MANTENIDO ni CONFIRMADA_BAJA (decisiones ya tomadas
        por Javiera: se respetan y no vuelven a esta bandeja).

        Agrega "MOTIVO" (texto amigable de ORIGEN_CASO, ver
        cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP) para que la pestaña
        distinga el motivo de revisión sin exponer el valor técnico.

        Las unidades cuya forma de contrato no es CM se gestionan en Ingresos y
        Conciliación > Contratos (CM), no aquí.

        No toca CasosBajaCM.csv ni PruebasFM: solo lee."""
        df_casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        df_pendientes = df_casos[df_casos['ESTADO_CASO'] == cm_bajas_service.ESTADO_CASO_PENDIENTE].copy()
        df_pendientes['MOTIVO'] = df_pendientes['ORIGEN_CASO'].map(
            cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP
        ).fillna(df_pendientes['ORIGEN_CASO'])
        # Running sin pago cuyo término aún no llega: es un aviso previo, no un contrato terminado
        if not df_pendientes.empty:
            es_rv = df_pendientes['ORIGEN_CASO'] == cm_bajas_service.ORIGEN_CASO_RUNNING_VENCIDO
            termino = pd.to_datetime(df_pendientes['FECHA TERMINO CM'], errors='coerce', format='%d-%m-%Y')
            por_vencer = es_rv & (termino.dt.normalize() >= pd.Timestamp.now().normalize())
            df_pendientes.loc[por_vencer, 'MOTIVO'] = "Por vencer sin pago"
        # Expired de una unidad que hoy ya no es CM: datos antiguos, no un contrato recién vencido
        vins_no_cm = ct_service.vins_forma_y_facturacion_no_cm(getattr(self.legacy, 'df_base', None))
        if vins_no_cm and not df_pendientes.empty:
            antiguos = ((df_pendientes['ORIGEN_CASO'] == cm_bajas_service.ORIGEN_CASO_ESTADO_EXPIRED)
                        & df_pendientes['VIN'].astype(str).str.strip().str.upper().isin(vins_no_cm))
            df_pendientes.loc[antiguos, 'MOTIVO'] = cm_bajas_service.MOTIVO_DATOS_CM_ANTIGUOS
        self._aplicar_estado_cm_vigente(df_pendientes)
        self._completar_columnas_cm(df_pendientes)
        return df_pendientes if not df_casos.empty else df_casos

    def _completar_columnas_cm(self, df_casos):
        """Columnas que el caso no guarda y que Contratos (CM) sí muestra: salen del contrato actual de la unidad."""
        df_base = getattr(self.legacy, 'df_base', None)
        if df_casos.empty or df_base is None or df_base.empty or 'VIN' not in df_base.columns:
            return
        base = df_base.assign(_VIN=df_base['VIN'].astype(str).str.strip().str.upper()) \
            .drop_duplicates('_VIN', keep='last').set_index('_VIN')
        vins = df_casos['VIN'].astype(str).str.strip().str.upper()
        origen = {'ACTIVACIÓN': 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO COMERCIAL': 'ESTADO COMERCIAL',
                  'ULTIMO PAGO CM': 'ULTIMO PAGO CM', 'FECHA ULTIMO PAGO CM': 'FECHA ULTIMO PAGO CM',
                  'OBSERVACIONES': 'OBSERVACIONES'}
        for destino, fuente in origen.items():
            if fuente in base.columns:
                df_casos[destino] = vins.map(base[fuente].astype(str).str.strip()).fillna('')
        if 'OBSERVACIONES' in df_casos.columns:
            df_casos['GESTIÓN'] = df_casos['OBSERVACIONES'].map(comercial_services.estado_gestion_cm)

    def _aplicar_estado_cm_vigente(self, df_casos):
        """El caso guarda el ESTADO DEL CM del momento en que se detectó; la
        bandeja muestra el actual del contrato (p. ej. Pendiente)."""
        df_base = getattr(self.legacy, 'df_base', None)
        if df_casos.empty or df_base is None or df_base.empty \
                or not {'VIN', 'ESTADO DEL CM'} <= set(df_base.columns):
            return
        actual = df_base.assign(_VIN=df_base['VIN'].astype(str).str.strip().str.upper()) \
            .drop_duplicates('_VIN', keep='last').set_index('_VIN')['ESTADO DEL CM'].astype(str).str.strip()
        nuevo = df_casos['VIN'].astype(str).str.strip().str.upper().map(actual)
        df_casos['ESTADO DEL CM'] = nuevo.where(nuevo.notna() & (nuevo != ''), df_casos['ESTADO DEL CM'])
