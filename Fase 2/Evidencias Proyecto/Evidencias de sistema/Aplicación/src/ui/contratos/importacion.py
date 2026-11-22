"""Importación del Excel de contratos CM: análisis, resumen y alta de contratos nuevos."""
import os
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import QMessageBox, QFileDialog, QApplication, QDialog
from PyQt6.QtCore import Qt
import config.settings
from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
from src.services import cm_bajas_service
from src.services import comercial_services
from src.services import contratos_service as ct_service
from src.core.constants import COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, TIPO_CM_FORMA_CONTRATO_MAP, VALOR_TIPO_FACT_CM, ESTADOS_CM_SIN_PAGO, ESTADO_CM_PENDIENTE
from src.ui.contratos.base import logger, SaveContratosThread, AnalisisImportacionThread
from src.ui.contratos.dialogos import VinsNuevosContratoAlertDialog, VincularContratoComercialDialog
from src.ui.contratos.importacion_dialogo import ResumenImportacionDialog
from src.ui.contratos.base import (
    AnalisisImportacionThread,
    SaveContratosThread,
    logger,
)
from src.ui.contratos.dialogos import (
    VincularContratoComercialDialog,
    VinsNuevosContratoAlertDialog,
)
from src.ui.contratos.importacion_dialogo import (
    ResumenImportacionDialog,
)


class _ImportacionContratosMixin:
    # =========================================================
    # IMPORTACIÓN MASIVA (sin cambios de comportamiento)
    # =========================================================
    def importar_excel_javiera(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleccionar Excel de Contratos", "", "Excel (*.xlsx *.xls)")
        if not filepath: return

        if self.window().isVisible():
            self._analizar_en_segundo_plano(filepath)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resultado = self._analizar_importacion(filepath)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error al importar", f"Ocurrió un problema:\n{str(e)}")
            return
        QApplication.restoreOverrideCursor()
        self._mostrar_resumen_importacion(filepath, resultado)

    def _analizar_en_segundo_plano(self, filepath):
        import src.ui.comercial_agregar  # noqa: F401 (se importa aquí, no en el hilo)
        mostrar_guardando(self, "Cargando datos del 3PC…", sub="Leyendo el archivo y comparándolo con la Base Comercial.",
                          demora="Está tardando más de lo normal. La carga sigue en curso.")
        self._analisis_thread = AnalisisImportacionThread(self._analizar_importacion, filepath)
        self._analisis_thread.terminado.connect(lambda resultado, error: self._on_analisis_terminado(filepath, resultado, error))
        self._analisis_thread.start()

    def _on_analisis_terminado(self, filepath, resultado, error):
        terminar_guardando(self, exito=False)
        if error:
            QMessageBox.critical(self, "Error al importar", f"Ocurrió un problema:\n{error}")
            return
        self._mostrar_resumen_importacion(filepath, resultado)

    def _analizar_importacion(self, filepath):
        """Lee el 3PC y lo compara con el RM; corre en un hilo. Devuelve lo que
        necesita el resumen: no toca ningún widget."""
        df_import = ct_service.leer_excel_3pc(filepath)
        df_import.columns = df_import.columns.astype(str).str.strip().str.upper()

        col_vin = next((c for c in df_import.columns if 'VIN NO' in c or 'VIN' in c), None)
        col_contrato = next((c for c in df_import.columns if 'CONTRACT NO' in c), None)
        col_inicio = next((c for c in df_import.columns if 'START DATE' in c), None)
        col_termino = next((c for c in df_import.columns if 'EXPIRING DATE' in c), None)
        col_estado = next((c for c in df_import.columns if 'CONTRACT STATUS' in c), None)
        col_tipo = next((c for c in df_import.columns if 'CONTRACT TYPE' in c), None)
        col_pago = next((c for c in df_import.columns if 'NET AMOUNT' in c), None)
        col_cliente = next((c for c in df_import.columns if 'CUSTOMER NAME' in c), None)
        col_fecha_pago = next((c for c in df_import.columns if 'CLAIM PAY DATE' in c), None)

        if not col_vin:
            raise Exception("El archivo no contiene una columna identificable de VIN (Ej. 'VIN No').")

        df_import['VIN_CLEAN'] = df_import[col_vin].astype(str).str.replace(r'\s+', '', regex=True).str.upper()
        # Mes que cubre el 3PC: el más reciente con pagos. Una unidad cuyo último pago es de un mes
        # anterior no pagó este mes: su pago no cuenta y queda solo como histórico.
        col_mes_pago = next((c for c in df_import.columns if 'CLAIM PAY MONTH' in c), None) \
            or next((c for c in df_import.columns if 'CLAIM PAY DATE' in c), None)
        mes_pago = pd.to_datetime(df_import[col_mes_pago], errors='coerce').dt.to_period('M') if col_mes_pago else None
        mes_referencia = mes_pago.max() if mes_pago is not None else None
        if mes_pago is not None:
            df_import['_MES_PAGO'] = mes_pago
        # El 3PC trae una fila por cada mes pagado (los atrasados se pagan juntos) y notas de crédito
        # en negativo: por VIN se toma la última fila con importe positivo, que es la mensualidad.
        if col_pago:
            importe_positivo = pd.to_numeric(df_import[col_pago], errors='coerce').fillna(0) > 0
            df_import = df_import.assign(_NO_POSITIVO=~importe_positivo).sort_values('_NO_POSITIVO', ascending=False, kind='stable')
        df_import = df_import.drop_duplicates(subset=['VIN_CLEAN'], keep='last')
        df_import = df_import.set_index('VIN_CLEAN')

        df_master = comercial_services.contratos_actuales(self.data_manager.df_master)
        vins_comercial = df_master['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper().tolist()

        # --- DETECCIÓN DE POSIBLES BAJAS CM (separada de la actualización normal) ---
        # detectar_posibles_bajas_cm() es pura (no persiste nada): se usa
        # aca para mostrar los VIN ausentes en ResumenImportacionDialog,
        # y ademas se persiste mas abajo via procesar_deteccion_baja_cm
        # (mismo criterio que ya usa Gestionar CM, sin duplicar logica).
        vins_ausentes_info = []
        try:
            vins_ausentes_info = cm_bajas_service.detectar_posibles_bajas_cm(
                df_pruebas_antes=df_master.copy(),
                vins_en_nuevo_listado=list(df_import.index),
                periodo_deteccion=datetime.now().strftime('%Y-%m'),
            )
            cm_bajas_service.procesar_deteccion_baja_cm(
                df_pruebas_antes=df_master.copy(),
                vins_en_nuevo_listado=list(df_import.index),
                periodo_deteccion=datetime.now().strftime('%Y-%m'),
                casos_path=config.settings.CASOS_BAJA_CM_PATH,
            )
        except Exception as e:
            logger.error(f"No se pudo actualizar los casos de posible Baja CM: {e}")

        cambios_comercial = {}

        def limpiar_fecha(val):
            if pd.isna(val) or str(val).strip() in ['NaT', 'nan', '']: return "-"
            try: return pd.to_datetime(val).strftime("%d-%m-%Y")
            except Exception: return str(val)

        # FORMA DE CONTRATO que pasa siempre a CMG/CMB/CMS (30-09-2026, y
        # "Revisar" desde el 26-10-2026, confirmado por Javiera). Provisión,
        # Provisión +, Conversión y Venta no se pisan solas: pasarlas a CM
        # es opcional (ver cambios_opcionales y el interruptor del resumen).
        FORMAS_CONTRATO_SOBREESCRIBIBLES = ct_service.FORMAS_QUE_PASAN_A_CM

        def datos_cm_de_fila(row, estado_cm_anterior=None, forma_contrato_anterior=None):
            cambios = {}
            cambios['N CONTRATO 3PC'] = str(row.get(col_contrato, '-')) if pd.notna(row.get(col_contrato)) else '-'
            cambios['FECHA INICIO CM'] = limpiar_fecha(row.get(col_inicio))
            cambios['FECHA TERMINO CM'] = limpiar_fecha(row.get(col_termino))
            cambios['TIPO DE CM'] = str(row.get(col_tipo, '-')) if pd.notna(row.get(col_tipo)) else '-'
            cambios['ESTADO DEL CM'] = str(row.get(col_estado, '-')) if pd.notna(row.get(col_estado)) else '-'
            mes_ultimo_pago = row.get('_MES_PAGO')
            sin_pago_este_mes = (mes_referencia is not None and pd.notna(mes_ultimo_pago)
                                 and mes_ultimo_pago < mes_referencia)
            # Running con el término ya vencido y sin pago este mes: el 3PC todavía no lo cierra, la app lo pasa a Expired
            termino = pd.to_datetime(row.get(col_termino), errors='coerce') if col_termino else pd.NaT
            if (cambios['ESTADO DEL CM'].strip().upper() == 'RUNNING' and sin_pago_este_mes
                    and pd.notna(termino) and termino.normalize() < pd.Timestamp.now().normalize()):
                cambios['ESTADO DEL CM'] = 'Expired'
            # Una unidad Pendiente que el 3PC sigue trayendo Expired es el mismo caso sin resolver: sigue Pendiente
            if (estado_cm_anterior is not None and cambios['ESTADO DEL CM'].strip().upper() == 'EXPIRED'
                    and str(estado_cm_anterior).strip().upper() == ESTADO_CM_PENDIENTE.upper()):
                cambios['ESTADO DEL CM'] = ESTADO_CM_PENDIENTE
            try:
                pago_val = float(row.get(col_pago, 0))
                # Bug real detectado (30-09-2026, simulación contra copia
                # de RM_JAVI.csv real): guardar un float acá rompía el
                # guardado completo en el backend CSV real (dtype=str),
                # que aborta con "Invalid value ... for dtype 'str'" al
                # intentar escribir un float -- fallaba en silencio
                # (success=False) y ningún cambio del import masivo
                # quedaba guardado. Los tests existentes no lo detectaban
                # porque prueban contra el backend .xlsx legado, no
                # contra el .csv real. Se guarda como texto, igual que
                # el resto de las columnas de RM_JAVI.csv.
                cambios['PAGO CM'] = str(pago_val) if pd.notna(pago_val) else '0.0'
            except Exception:
                cambios['PAGO CM'] = '0.0'
            # Histórico: el último pago positivo con su fecha queda guardado aunque PAGO CM pase a 0
            importe_ultimo = pd.to_numeric(row.get(col_pago), errors='coerce') if col_pago else float('nan')
            if pd.notna(importe_ultimo) and importe_ultimo > 0:
                cambios[COL_ULTIMO_PAGO_CM] = str(float(importe_ultimo))
                cambios[COL_FECHA_ULTIMO_PAGO_CM] = limpiar_fecha(row.get(col_fecha_pago))
            if sin_pago_este_mes:
                cambios['PAGO CM'] = '0.0'

            # Regla de negocio confirmada (30-09-2026): un TIPO DE CM
            # Gold/Blue/Silver implica FORMA DE CONTRATO=CMG/CMB/CMS y
            # TIPO DE FACTURACION=CM, tanto en VIN nuevos como ya
            # existentes en Comercial -- pero solo si la FORMA DE
            # CONTRATO actual no es ya una clasificación de negocio
            # distinta (ver FORMAS_CONTRATO_SOBREESCRIBIBLES arriba). Un
            # TIPO DE CM sin mapeo ('-' o 'Current Contract Type') no
            # fuerza ningún cambio acá.
            forma_contrato = TIPO_CM_FORMA_CONTRATO_MAP.get(cambios['TIPO DE CM'])
            forma_contrato_previa_norm = str(forma_contrato_anterior).strip().upper() if forma_contrato_anterior is not None else ''
            if forma_contrato and forma_contrato_previa_norm in FORMAS_CONTRATO_SOBREESCRIBIBLES:
                cambios['FORMA DE CONTRATO'] = forma_contrato
                cambios['TIPO DE FACTURACION'] = VALOR_TIPO_FACT_CM

            # ESTADO COMERCIAL (30-09-2026, corregido a pedido explícito:
            # mismo criterio que ESTADO DE ACTIVACIÓN ACTUAL): un VIN que
            # ya existe en Comercial NO se toca, salvo que su ESTADO DEL
            # CM recién pase a "Expired" con ESTE import (no lo estaba
            # antes) -- ahí sí se marca "Revisar" para que alguien lo
            # mire. `estado_cm_anterior=None` (VIN nuevo, ver
            # contratos_service.construir_registro_nuevo_desde_contrato_cm)
            # no aplica esta condición: ese caso ya queda en "Revisar"
            # por default, igual que cualquier unidad creada desde cero.
            paso_a_expired_ahora = (
                cambios['ESTADO DEL CM'].strip().upper() == 'EXPIRED'
                and estado_cm_anterior is not None
                and str(estado_cm_anterior).strip().upper() not in ESTADOS_CM_SIN_PAGO
            )
            if paso_a_expired_ahora:
                # Expired sin pago este mes: el contrato venció, queda Vencido; con pago, alguien lo revisa
                cambios['ESTADO COMERCIAL'] = 'Vencido' if sin_pago_este_mes else 'Revisar'
            return cambios

        estado_cm_actual_por_vin = dict(zip(vins_comercial, df_master.get('ESTADO DEL CM', pd.Series(dtype=str))))
        forma_contrato_actual_por_vin = dict(zip(vins_comercial, df_master.get('FORMA DE CONTRATO', pd.Series(dtype=str))))

        filas_actuales_por_vin = dict(zip(vins_comercial, df_master.to_dict('records')))
        nuevos_info = []
        cambios_opcionales = {}

        for vin in vins_comercial:
            if vin == 'NAN' or not vin: continue

            if vin not in df_import.index:
                # Regla de negocio confirmada con Javiera: que un VIN
                # desaparezca del Excel mensual de CM NO confirma una
                # baja. La fila simplemente no se toca.
                continue

            # Contrato actual en baja: es de solo lectura, nunca se
            # actualiza. Si la unidad viene en el 3PC y está Desconectada se
            # crea un contrato nuevo con los datos del anterior que va a
            # activarse en Operaciones; si no, solo cuando su CM llega
            # Expired y la matriz de nuevo contrato lo admite.
            fila_actual = filas_actuales_por_vin.get(vin, {})
            if comercial_services.es_contrato_cerrado(fila_actual.get('ESTADO COMERCIAL', '')):
                fila_cm = datos_cm_de_fila(df_import.loc[vin])
                if ct_service.es_desconectada_en_baja(fila_actual):
                    nuevos_info.append((vin, fila_actual, fila_cm, 'desconectada'))
                elif (str(fila_cm.get('ESTADO DEL CM', '')).strip().upper() == 'EXPIRED'
                        and comercial_services.puede_crear_contrato(
                            fila_actual.get('ESTADO COMERCIAL', ''), fila_actual.get('ESTADO DE ACTIVACIÓN ACTUAL', ''))):
                    nuevos_info.append((vin, fila_actual, fila_cm, 'expired'))
                continue

            # CM vencido que el 3PC sigue listando de una unidad que ya no es CM y quedó sin datos CM
            # (p. ej. tras "Limpiar datos CM"): no se vuelven a cargar
            if ct_service.omitir_en_importacion(df_import.loc[vin].get(col_estado, ''), fila_actual):
                continue

            cambios_comercial[vin] = {
                'VIN': vin,
                'cambios': datos_cm_de_fila(
                    df_import.loc[vin],
                    estado_cm_anterior=estado_cm_actual_por_vin.get(vin),
                    forma_contrato_anterior=forma_contrato_actual_por_vin.get(vin),
                )
            }
            opcional = ct_service.cambio_opcional_a_cm(
                cambios_comercial[vin]['cambios']['TIPO DE CM'], forma_contrato_actual_por_vin.get(vin, ''))
            if opcional:
                cambios_opcionales[vin] = opcional

        # El CM actualiza solo el contrato actual del VIN, no los anteriores
        comercial_services.agregar_id_a_cambios(cambios_comercial, df_master)

        # --- VIN del Excel que NO tienen fila en Comercial (RM) ---
        # Antes quedaban ignorados en silencio (nunca se creaba la
        # ficha ni se completaba Razón Social/RUT/etc). Mismo camino
        # que Provisiones (VincularComercialDialog): se ofrece
        # vincularlos con un cliente ya existente usando el nombre que
        # trae el propio Excel de Javiera (Current Invoicing Customer
        # Name), en vez de crearlos a ciegas.
        vins_comercial_set = set(vins_comercial)
        vins_nuevos_info = []
        if col_cliente:
            for vin in df_import.index:
                if vin == 'NAN' or not vin or vin in vins_comercial_set:
                    continue
                row = df_import.loc[vin]
                info = {'VIN': vin, 'CLIENTE': str(row.get(col_cliente, '-')) if pd.notna(row.get(col_cliente)) else '-'}
                info.update(datos_cm_de_fila(row))
                vins_nuevos_info.append(info)
        self.import_vins_nuevos = vins_nuevos_info


        return {
            'df_master': df_master, 'total_filas': len(df_import), 'cambios_comercial': cambios_comercial,
            'nuevos_info': nuevos_info, 'vins_ausentes_info': vins_ausentes_info, 'vins_nuevos_info': vins_nuevos_info,
            'cambios_opcionales': cambios_opcionales,
        }

    def _armar_contratos_nuevos(self, nuevos_info):
        """Contratos nuevos con su ID: copiados del anterior (unidad desconectada en
        baja) o armados desde el 3PC (baja con CM Expired)."""
        from src.ui.comercial_agregar import _MESES
        ahora = datetime.now()
        periodo = f"{_MESES[ahora.month - 1]} - {ahora.year}".lower()
        siguiente_id = comercial_services.proximo_id_contrato(self.data_manager.df_master)
        nuevos = []
        for vin, fila_actual, fila_cm, motivo in nuevos_info:
            if motivo == 'desconectada':
                registro = ct_service.construir_contrato_nuevo_desde_anterior(fila_actual, fila_cm, periodo)
            else:
                registro = ct_service.construir_registro_nuevo_desde_contrato_cm(vin, fila_cm, fila_actual)
                for campo in ('INDUSTRIA', 'FLOTA VC', 'FLOTA VC 2', 'CDB FLOTA'):
                    if str(fila_actual.get(campo, '')).strip() not in ('', 'nan'):
                        registro[campo] = fila_actual[campo]
                registro['PERIODO INTERNO'] = periodo
            if siguiente_id:
                registro['ID'] = siguiente_id
                siguiente_id = str(int(siguiente_id) + 1)
            nuevos.append(registro)
        return nuevos

    def _mostrar_resumen_importacion(self, filepath, resultado):
        cambios_comercial = resultado['cambios_comercial']
        vins_nuevos_info = resultado['vins_nuevos_info']
        cambios_opcionales = resultado['cambios_opcionales']
        contratos_nuevos = self._armar_contratos_nuevos(resultado['nuevos_info'])

        if cambios_comercial or contratos_nuevos:
            resumen = ct_service.calcular_resumen_importacion(
                resultado['df_master'], cambios_comercial, resultado['total_filas'],
                resultado['vins_ausentes_info'], vins_nuevos_info, contratos_nuevos, cambios_opcionales,
            )
            dialogo = ResumenImportacionDialog(resumen, os.path.basename(filepath), self)
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                autorizados = dialogo.vins_autorizados()
                df_actuales = resultado['df_master'].drop_duplicates('VIN', keep='last')
                filas_actuales = dict(zip(
                    df_actuales['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper(), df_actuales.to_dict('records')))
                siguiente_id = comercial_services.proximo_id_contrato(self.data_manager.df_master)
                ids_usados = [int(r['ID']) for r in contratos_nuevos if str(r.get('ID', '')).isdigit()]
                if siguiente_id and ids_usados:
                    siguiente_id = str(max(int(siguiente_id), max(ids_usados) + 1))
                for vin, cambios in cambios_opcionales.items():
                    if vin not in autorizados:
                        continue
                    fila = filas_actuales.get(vin)
                    if siguiente_id and fila is not None and ct_service.es_forma_provision(fila.get('FORMA DE CONTRATO', '')):
                        anterior, registro = ct_service.construir_renovacion_provision_a_cm(
                            {**fila, **cambios_comercial[vin]['cambios']}, cambios, siguiente_id)
                        siguiente_id = str(int(siguiente_id) + 1)
                        cambios_comercial[vin]['cambios'] = anterior
                        contratos_nuevos.append(registro)
                    else:
                        cambios_comercial[vin]['cambios'].update(cambios)
                for vin, datos in cambios_comercial.items():
                    if vin not in autorizados:
                        datos['cambios'].pop('FORMA DE CONTRATO', None)
                        datos['cambios'].pop('TIPO DE FACTURACION', None)
                self.btn_reload.setEnabled(False)
                self.btn_importar.setEnabled(False)

                self.lbl_loading_text.setText("Comparando e inyectando miles de contratos... Esto tomará unos segundos.")
                self.stack.setCurrentIndex(0)
                QApplication.processEvents()

                self.import_changes = cambios_comercial
                self.import_contratos_nuevos = contratos_nuevos

                self.save_thread = SaveContratosThread(
                    self.writer, cambios_comercial, "Contratos CM (Masivo)", contratos_nuevos)
                self.save_thread.finished_signal.connect(self._on_import_finished)
                self.save_thread.start()
        elif vins_nuevos_info:
            # Sin coincidencias para actualizar, pero el Excel trae VIN
            # que no tienen ficha en Comercial: se ofrece igual el
            # camino de vinculación, sin pasar por ResumenImportacionDialog
            # (no hay nada que "inyectar" sobre registros existentes).
            self._mostrar_alerta_vins_nuevos()

    def _on_import_finished(self, success):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)

        if success:
            df_m = self.data_manager.df_master.copy()
            if not df_m.empty:
                df_m = comercial_services.aplicar_cambios_pendientes(df_m, self.import_changes)
                for registro in getattr(self, 'import_contratos_nuevos', []):
                    df_m = comercial_services.agregar_fila(df_m, registro)
                self.import_contratos_nuevos = []
                self.data_manager.df_master = df_m

                try:
                    cm_bajas_service.procesar_reconciliacion_estado_expired(
                        df_pruebas_actual=comercial_services.contratos_actuales(self.data_manager.df_master),
                        periodo_deteccion=datetime.now().strftime('%Y-%m'),
                        casos_path=config.settings.CASOS_BAJA_CM_PATH,
                    )
                except Exception as e:
                    logger.error(f"No se pudo reconciliar los casos de Revisión CM por estado Expired: {e}")

                # Avisa a Comercial/Vista General que df_master cambió en RAM
                # (mismo patrón que VincularContratoComercialDialog._on_creado
                # y provisiones.py::_on_save_finished): sin esto, el import
                # masivo de CM solo se veía reflejado ahí tras un Recargar
                # manual.
                self.data_manager.data_ready.emit()

            self.load_data()
            self.stack.setCurrentIndex(1)
            self._mostrar_alerta_vins_nuevos()
        else:
            self.stack.setCurrentIndex(1)
            QMessageBox.warning(self, "Error", "No se pudo actualizar el Excel Comercial (puede estar bloqueado).")

    def _mostrar_alerta_vins_nuevos(self):
        vins_nuevos = getattr(self, 'import_vins_nuevos', [])
        if not vins_nuevos:
            return
        alerta = VinsNuevosContratoAlertDialog(vins_nuevos, self)
        if alerta.exec() == QDialog.DialogCode.Accepted:
            dialogo = VincularContratoComercialDialog(vins_nuevos, self.data_manager, self)
            dialogo.vin_resuelto.connect(lambda vin: self.load_data())
            dialogo.exec()
