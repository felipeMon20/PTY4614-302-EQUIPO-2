import os
import tempfile
import unittest
from datetime import datetime

import pandas as pd

from src.services.cm_bajas_service import (
    tiene_datos_cm, detectar_posibles_bajas_cm, actualizar_casos_baja_cm,
    leer_casos_baja_cm, guardar_casos_baja_cm, procesar_deteccion_baja_cm,
    detectar_casos_expired_actuales, reconciliar_casos_estado_expired,
    procesar_reconciliacion_estado_expired,
    confirmar_baja_caso, procesar_confirmacion_baja_cm,
    confirmar_baja_casos, procesar_confirmacion_baja_cm_multiple,
    ESTADO_CASO_PENDIENTE, ESTADO_CASO_REAPARECIDO, ESTADO_CASO_CONFIRMADA_BAJA,
    ORIGEN_CASO_AUSENCIA_3PC, ORIGEN_CASO_ESTADO_EXPIRED, CASOS_BAJA_CM_COLUMNS,
)


def _fila_cm(vin, n_contrato='3PC-1', estado_cm='Running'):
    return {
        'VIN': vin, 'CHASIS': 'C1', 'RAZÓN SOCIAL': 'Empresa X', 'FLOTA VC': 'Empresa X',
        'N CONTRATO 3PC': n_contrato, 'FECHA INICIO CM': '01-01-2025', 'FECHA TERMINO CM': '01-01-2026',
        'TIPO DE CM': 'Silver', 'ESTADO DEL CM': estado_cm, 'PAGO CM': 15000,
    }


class TestTieneDatosCm(unittest.TestCase):
    """'Estaba asociado a CM' no depende de una sola columna (ver
    cm_bajas_service.COLUMNAS_CM_ASOCIACION): alcanza con que N CONTRATO 3PC
    O ESTADO DEL CM tengan un valor real."""

    def test_con_numero_de_contrato_y_estado(self):
        self.assertTrue(tiene_datos_cm(_fila_cm('V1')))

    def test_con_solo_numero_de_contrato(self):
        self.assertTrue(tiene_datos_cm(_fila_cm('V1', n_contrato='3PC-1', estado_cm='-')))

    def test_con_solo_estado_cm(self):
        self.assertTrue(tiene_datos_cm(_fila_cm('V1', n_contrato='-', estado_cm='Running')))

    def test_sin_ningun_dato_cm(self):
        self.assertFalse(tiene_datos_cm(_fila_cm('V1', n_contrato='-', estado_cm='-')))

    def test_columnas_ausentes_no_revientan(self):
        self.assertFalse(tiene_datos_cm({'VIN': 'V1'}))


class TestDetectarPosiblesBajasCm(unittest.TestCase):

    def test_caso1_presente_antes_y_ahora_no_genera_deteccion(self):
        df_antes = pd.DataFrame([_fila_cm('V1')])
        detecciones = detectar_posibles_bajas_cm(df_antes, ['V1'], '2026-01')
        self.assertEqual(detecciones, [])

    def test_caso2_vin_nuevo_no_genera_deteccion(self):
        # VIN nuevo: no existia en PruebasFM antes, asi que no hay fila que
        # comparar -- nunca puede aparecer como deteccion.
        df_antes = pd.DataFrame([_fila_cm('V1')])
        detecciones = detectar_posibles_bajas_cm(df_antes, ['V1', 'V2_NUEVO'], '2026-01')
        self.assertEqual(detecciones, [])

    def test_caso3_desaparece_genera_deteccion(self):
        df_antes = pd.DataFrame([_fila_cm('V1')])
        detecciones = detectar_posibles_bajas_cm(df_antes, [], '2026-01')
        self.assertEqual(len(detecciones), 1)
        self.assertEqual(detecciones[0]['VIN'], 'V1')
        self.assertEqual(detecciones[0]['PERIODO_DETECCION'], '2026-01')

    def test_caso8_vin_nunca_tuvo_cm_no_genera_deteccion(self):
        df_antes = pd.DataFrame([_fila_cm('V1', n_contrato='-', estado_cm='-')])
        detecciones = detectar_posibles_bajas_cm(df_antes, [], '2026-01')
        self.assertEqual(detecciones, [])

    def test_caso9_no_modifica_df_pruebas_antes(self):
        df_antes = pd.DataFrame([_fila_cm('V1')])
        snapshot = df_antes.copy()
        detectar_posibles_bajas_cm(df_antes, [], '2026-01')
        pd.testing.assert_frame_equal(df_antes, snapshot)

    def test_normaliza_vin_espacios_y_mayusculas(self):
        df_antes = pd.DataFrame([_fila_cm(' v1 ')])
        detecciones = detectar_posibles_bajas_cm(df_antes, [], '2026-01')
        self.assertEqual(detecciones[0]['VIN'], 'V1')

    def test_df_vacio_no_revienta(self):
        self.assertEqual(detectar_posibles_bajas_cm(pd.DataFrame(), [], '2026-01'), [])


class TestActualizarCasosBajaCm(unittest.TestCase):
    """Cubre la deduplicacion (1 VIN + mismo evento pendiente = 1 caso) y la
    transicion PENDIENTE -> REAPARECIDO, simulando varios meses consecutivos
    encadenando llamadas (cada una representa una corrida mensual)."""

    def setUp(self):
        self.df_antes = pd.DataFrame([_fila_cm('V1')])

    def _mes_ausente(self, df_casos, periodo):
        detecciones = detectar_posibles_bajas_cm(self.df_antes, [], periodo)
        return actualizar_casos_baja_cm(df_casos, detecciones, [])

    def test_caso3_primera_desaparicion_crea_pendiente(self):
        df_casos = self._mes_ausente(pd.DataFrame(), '2026-01')
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['VIN'], 'V1')
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(df_casos.iloc[0]['MESES_CONSECUTIVOS_AUSENTE'], '1')

    def test_caso4_reimportar_mismo_archivo_no_duplica(self):
        df_casos = self._mes_ausente(pd.DataFrame(), '2026-01')
        df_casos = self._mes_ausente(df_casos, '2026-01')  # mismo mes, se reimporta
        self.assertEqual(len(df_casos), 1, "Fallo: no debe crearse un segundo caso para el mismo evento.")
        self.assertEqual(df_casos.iloc[0]['MESES_CONSECUTIVOS_AUSENTE'], '2')

    def test_caso5_mes_siguiente_sigue_ausente_mantiene_mismo_caso(self):
        df_casos = self._mes_ausente(pd.DataFrame(), '2026-01')
        df_casos = self._mes_ausente(df_casos, '2026-02')
        df_casos = self._mes_ausente(df_casos, '2026-03')
        self.assertEqual(len(df_casos), 1, "Fallo: varios meses ausente deben ser el mismo caso, no varios.")
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(df_casos.iloc[0]['MESES_CONSECUTIVOS_AUSENTE'], '3')

    def test_caso6_reaparece_cambia_a_reaparecido(self):
        df_casos = self._mes_ausente(pd.DataFrame(), '2026-01')
        # El VIN reaparece: SI esta en el nuevo listado este mes.
        df_casos = actualizar_casos_baja_cm(df_casos, [], ['V1'])

        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_REAPARECIDO)

    def test_caso7_desaparece_de_nuevo_tras_reaparecer_crea_nuevo_pendiente(self):
        df_casos = self._mes_ausente(pd.DataFrame(), '2026-01')
        df_casos = actualizar_casos_baja_cm(df_casos, [], ['V1'])  # reaparece
        df_casos = self._mes_ausente(df_casos, '2026-05')  # desaparece de nuevo

        self.assertEqual(len(df_casos), 2, "Fallo: debe crearse un caso PENDIENTE nuevo, sin tocar el REAPARECIDO.")
        estados = sorted(df_casos['ESTADO_CASO'].tolist())
        self.assertEqual(estados, [ESTADO_CASO_PENDIENTE, ESTADO_CASO_REAPARECIDO])

        caso_reaparecido = df_casos[df_casos['ESTADO_CASO'] == ESTADO_CASO_REAPARECIDO].iloc[0]
        caso_pendiente = df_casos[df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE].iloc[0]
        self.assertNotEqual(caso_reaparecido['CASO_ID'], caso_pendiente['CASO_ID'])
        self.assertEqual(caso_pendiente['MESES_CONSECUTIVOS_AUSENTE'], '1', "Fallo: el caso nuevo debe empezar en 1.")

    def test_caso_id_es_incremental_y_no_se_repite(self):
        df_antes_dos_vin = pd.DataFrame([_fila_cm('V1'), _fila_cm('V2')])
        detecciones = detectar_posibles_bajas_cm(df_antes_dos_vin, [], '2026-01')
        df_casos = actualizar_casos_baja_cm(pd.DataFrame(), detecciones, [])
        self.assertEqual(len(df_casos), 2)
        self.assertEqual(len(set(df_casos['CASO_ID'])), 2)

    def test_no_modifica_lista_de_detecciones_original(self):
        detecciones = detectar_posibles_bajas_cm(self.df_antes, [], '2026-01')
        snapshot = [dict(d) for d in detecciones]
        actualizar_casos_baja_cm(pd.DataFrame(), detecciones, [])
        self.assertEqual(detecciones, snapshot)


class TestPersistenciaCasosBajaCm(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "sub", "CasosBajaCM.csv")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_leer_archivo_inexistente_devuelve_vacio_con_esquema(self):
        df = leer_casos_baja_cm(self.path)
        self.assertTrue(df.empty)
        self.assertIn('VIN', df.columns)
        self.assertIn('ESTADO_CASO', df.columns)

    def test_guardar_y_releer_conserva_los_datos(self):
        df_antes = pd.DataFrame([_fila_cm('V1')])
        detecciones = detectar_posibles_bajas_cm(df_antes, [], '2026-01')
        df_casos = actualizar_casos_baja_cm(pd.DataFrame(), detecciones, [])

        guardar_casos_baja_cm(df_casos, self.path)
        self.assertTrue(os.path.exists(self.path))

        df_releido = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_releido), 1)
        self.assertEqual(df_releido.iloc[0]['VIN'], 'V1')
        self.assertEqual(df_releido.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)

    def test_guardar_sin_path_no_revienta(self):
        guardar_casos_baja_cm(pd.DataFrame(), "")


class TestProcesarDeteccionBajaCmIntegracion(unittest.TestCase):
    """Simula el flujo completo mes a mes usando el archivo persistido real,
    igual que lo llamaria contratos.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "CasosBajaCM.csv")
        self.df_antes = pd.DataFrame([_fila_cm('V1')])

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_flujo_mes_a_mes_no_duplica_y_detecta_reaparicion(self):
        # Mes 1: VIN presente -> sin casos.
        procesar_deteccion_baja_cm(self.df_antes, ['V1'], '2026-01', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertTrue(df_casos.empty)

        # Mes 2: desaparece.
        procesar_deteccion_baja_cm(self.df_antes, [], '2026-02', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)

        # Mes 3: se reimporta el mismo archivo del mes 2 (sigue ausente).
        procesar_deteccion_baja_cm(self.df_antes, [], '2026-02', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_casos), 1, "Fallo: no debe duplicarse el caso.")

        # Mes 4: reaparece.
        procesar_deteccion_baja_cm(self.df_antes, ['V1'], '2026-04', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_REAPARECIDO)

    def test_no_toca_pruebasfm(self):
        snapshot = self.df_antes.copy()
        procesar_deteccion_baja_cm(self.df_antes, [], '2026-01', self.path)
        pd.testing.assert_frame_equal(self.df_antes, snapshot)


class TestDetectarCasosExpiredActuales(unittest.TestCase):
    """A diferencia de detectar_posibles_bajas_cm, esta deteccion no compara
    contra una version anterior: mira el estado ACTUAL de ESTADO DEL CM."""

    def test_vin_expired_genera_deteccion(self):
        df = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        detecciones = detectar_casos_expired_actuales(df, '2026-01')
        self.assertEqual(len(detecciones), 1)
        self.assertEqual(detecciones[0]['VIN'], 'V1')
        self.assertEqual(detecciones[0]['PERIODO_DETECCION'], '2026-01')

    def test_es_insensible_a_mayusculas(self):
        df = pd.DataFrame([_fila_cm('V1', estado_cm='EXPIRED')])
        self.assertEqual(len(detectar_casos_expired_actuales(df, '2026-01')), 1)

    def test_vin_running_no_genera_deteccion(self):
        df = pd.DataFrame([_fila_cm('V1', estado_cm='Running')])
        self.assertEqual(detectar_casos_expired_actuales(df, '2026-01'), [])

    def test_vin_terminated_no_genera_deteccion(self):
        df = pd.DataFrame([_fila_cm('V1', estado_cm='Terminated')])
        self.assertEqual(detectar_casos_expired_actuales(df, '2026-01'), [])

    def test_df_vacio_no_revienta(self):
        self.assertEqual(detectar_casos_expired_actuales(pd.DataFrame(), '2026-01'), [])

    def test_no_modifica_df_pruebas_actual(self):
        df = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        snapshot = df.copy()
        detectar_casos_expired_actuales(df, '2026-01')
        pd.testing.assert_frame_equal(df, snapshot)


class TestReconciliarCasosEstadoExpired(unittest.TestCase):
    """Cubre creacion, deduplicacion y cierre (Expired -> Running/Terminated)
    del carril ORIGEN_CASO=ESTADO_EXPIRED, y su aislamiento total respecto
    del carril ORIGEN_CASO=AUSENCIA_3PC aunque compartan VIN."""

    def _mes(self, df_casos, df_actual, periodo):
        detecciones = detectar_casos_expired_actuales(df_actual, periodo)
        vins_expired = df_actual.loc[
            df_actual['ESTADO DEL CM'].astype(str).str.upper() == 'EXPIRED', 'VIN'
        ].tolist() if not df_actual.empty else []
        return reconciliar_casos_estado_expired(df_casos, detecciones, vins_expired)

    def test_running_a_expired_genera_caso_pendiente(self):
        df_actual = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_actual, '2026-01')
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['VIN'], 'V1')
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(df_casos.iloc[0]['ORIGEN_CASO'], ORIGEN_CASO_ESTADO_EXPIRED)

    def test_no_duplica_si_ya_existe_pendiente_del_mismo_origen(self):
        df_actual = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_actual, '2026-01')
        df_casos = self._mes(df_casos, df_actual, '2026-02')  # sigue Expired
        self.assertEqual(len(df_casos), 1, "Fallo: no debe duplicarse el caso mientras siga Expired.")

    def test_expired_a_running_resuelve_el_caso(self):
        df_expired = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_expired, '2026-01')

        df_running = pd.DataFrame([_fila_cm('V1', estado_cm='Running')])
        df_casos = self._mes(df_casos, df_running, '2026-02')

        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_REAPARECIDO)

    def test_expired_a_terminated_resuelve_el_caso(self):
        df_expired = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_expired, '2026-01')

        df_terminated = pd.DataFrame([_fila_cm('V1', estado_cm='Terminated')])
        df_casos = self._mes(df_casos, df_terminated, '2026-02')

        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_REAPARECIDO)

    def test_vuelve_a_expired_tras_resolverse_crea_nuevo_caso(self):
        df_expired = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_expired, '2026-01')

        df_running = pd.DataFrame([_fila_cm('V1', estado_cm='Running')])
        df_casos = self._mes(df_casos, df_running, '2026-02')  # resuelve

        df_casos = self._mes(df_casos, df_expired, '2026-03')  # vuelve a Expired

        self.assertEqual(len(df_casos), 2, "Fallo: debe crear un caso nuevo, sin tocar el REAPARECIDO anterior.")
        estados = sorted(df_casos['ESTADO_CASO'].tolist())
        self.assertEqual(estados, [ESTADO_CASO_PENDIENTE, ESTADO_CASO_REAPARECIDO])

    def test_no_toca_casos_ausencia_3pc_del_mismo_vin(self):
        """Aislamiento critico (ver requisito 8 de la tarea): un VIN puede
        tener un caso PENDIENTE por AUSENCIA_3PC y NO debe cerrarse solo
        porque ESTADO DEL CM no sea Expired."""
        df_casos_ausencia = pd.DataFrame([{
            **{c: '' for c in CASOS_BAJA_CM_COLUMNS},
            'CASO_ID': '1', 'VIN': 'V1', 'ESTADO_CASO': ESTADO_CASO_PENDIENTE,
            'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC,
        }])[CASOS_BAJA_CM_COLUMNS]

        # V1 sigue Running en PruebasFM (nunca estuvo Expired) -- la
        # reconciliacion de Expired no debe tocar el caso de ausencia.
        df_actual = pd.DataFrame([_fila_cm('V1', estado_cm='Running')])
        df_resultado = self._mes(df_casos_ausencia, df_actual, '2026-01')

        self.assertEqual(len(df_resultado), 1)
        self.assertEqual(df_resultado.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE,
                          "Fallo: un caso AUSENCIA_3PC no debe cerrarse por logica de ESTADO_EXPIRED.")
        self.assertEqual(df_resultado.iloc[0]['ORIGEN_CASO'], ORIGEN_CASO_AUSENCIA_3PC)

    def test_vin_puede_tener_ambos_origenes_a_la_vez(self):
        """Un VIN puede estar ESTADO DEL CM=Running con un caso pendiente de
        AUSENCIA_3PC (valido, ver requisito 5) y, en un momento distinto,
        tambien generar un caso ESTADO_EXPIRED sin que se mezclen."""
        df_casos_ausencia = pd.DataFrame([{
            **{c: '' for c in CASOS_BAJA_CM_COLUMNS},
            'CASO_ID': '1', 'VIN': 'V1', 'ESTADO_CASO': ESTADO_CASO_PENDIENTE,
            'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC,
        }])[CASOS_BAJA_CM_COLUMNS]

        df_actual = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_resultado = self._mes(df_casos_ausencia, df_actual, '2026-01')

        self.assertEqual(len(df_resultado), 2)
        origenes = sorted(df_resultado['ORIGEN_CASO'].tolist())
        self.assertEqual(origenes, [ORIGEN_CASO_AUSENCIA_3PC, ORIGEN_CASO_ESTADO_EXPIRED])
        self.assertTrue((df_resultado['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE).all())

    def test_df_casos_vacio_no_revienta(self):
        df_actual = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        df_casos = self._mes(pd.DataFrame(), df_actual, '2026-01')
        self.assertEqual(len(df_casos), 1)


class TestActualizarCasosBajaCmNoTocaCasosExpired(unittest.TestCase):
    """Contraparte de TestReconciliarCasosEstadoExpired.test_no_toca_casos_
    ausencia_3pc_del_mismo_vin: la logica de AUSENCIA_3PC tampoco debe leer
    ni cerrar un caso ESTADO_EXPIRED del mismo VIN."""

    def test_reaparicion_en_3pc_no_cierra_caso_expired(self):
        df_casos_expired = pd.DataFrame([{
            **{c: '' for c in CASOS_BAJA_CM_COLUMNS},
            'CASO_ID': '1', 'VIN': 'V1', 'ESTADO_CASO': ESTADO_CASO_PENDIENTE,
            'ORIGEN_CASO': ORIGEN_CASO_ESTADO_EXPIRED,
        }])[CASOS_BAJA_CM_COLUMNS]

        # V1 "reaparece" en el 3PC mensual -- esto es AUSENCIA_3PC, no debe
        # afectar el caso ESTADO_EXPIRED existente.
        df_resultado = actualizar_casos_baja_cm(df_casos_expired, [], ['V1'])

        self.assertEqual(len(df_resultado), 1)
        self.assertEqual(df_resultado.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE,
                          "Fallo: un caso ESTADO_EXPIRED no debe cerrarse por logica de AUSENCIA_3PC.")


class TestProcesarReconciliacionEstadoExpiredIntegracion(unittest.TestCase):
    """Simula el flujo completo (guardar/importar -> reconciliar -> releer)
    usando el archivo persistido real, igual que lo llamarian comercial.py
    y contratos.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "CasosBajaCM.csv")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_flujo_running_expired_running(self):
        # Mes 1: Running -> sin casos.
        df_running = pd.DataFrame([_fila_cm('V1', estado_cm='Running')])
        procesar_reconciliacion_estado_expired(df_running, '2026-01', self.path)
        self.assertTrue(leer_casos_baja_cm(self.path).empty)

        # Mes 2: pasa a Expired -> genera caso.
        df_expired = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        procesar_reconciliacion_estado_expired(df_expired, '2026-02', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(df_casos.iloc[0]['ORIGEN_CASO'], ORIGEN_CASO_ESTADO_EXPIRED)

        # Mes 3: se reguarda sin cambios (sigue Expired) -> no duplica.
        procesar_reconciliacion_estado_expired(df_expired, '2026-03', self.path)
        self.assertEqual(len(leer_casos_baja_cm(self.path)), 1)

        # Mes 4: se renueva (vuelve a Running) -> se resuelve el caso.
        procesar_reconciliacion_estado_expired(df_running, '2026-04', self.path)
        df_casos = leer_casos_baja_cm(self.path)
        self.assertEqual(len(df_casos), 1)
        self.assertEqual(df_casos.iloc[0]['ESTADO_CASO'], ESTADO_CASO_REAPARECIDO)

    def test_no_toca_pruebasfm(self):
        df_expired = pd.DataFrame([_fila_cm('V1', estado_cm='Expired')])
        snapshot = df_expired.copy()
        procesar_reconciliacion_estado_expired(df_expired, '2026-01', self.path)
        pd.testing.assert_frame_equal(df_expired, snapshot)


class TestCompatibilidadOrigenCasoCsvViejo(unittest.TestCase):
    """CSV de produccion generado antes de que existiera ORIGEN_CASO: debe
    migrarse en memoria a AUSENCIA_3PC al leerse, sin tocar el archivo."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "CasosBajaCM_viejo.csv")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_csv_sin_columna_origen_caso_se_migra_a_ausencia_3pc(self):
        columnas_viejas = [c for c in CASOS_BAJA_CM_COLUMNS if c != 'ORIGEN_CASO']
        df_viejo = pd.DataFrame([{c: '' for c in columnas_viejas}])
        df_viejo.loc[0, 'CASO_ID'] = '1'
        df_viejo.loc[0, 'VIN'] = 'V1'
        df_viejo.loc[0, 'ESTADO_CASO'] = ESTADO_CASO_PENDIENTE
        df_viejo.to_csv(self.path, index=False)

        df_releido = leer_casos_baja_cm(self.path)
        self.assertIn('ORIGEN_CASO', df_releido.columns)
        self.assertEqual(df_releido.iloc[0]['ORIGEN_CASO'], ORIGEN_CASO_AUSENCIA_3PC)


class TestConfirmarBajaCaso(unittest.TestCase):
    """Etapa de revision (Confirmar baja) para un caso puntual, seleccionado
    a mano en Gestionar CM (ver comercial.py). A diferencia de
    reconciliar_casos_estado_expired, no evalua el estado actual de
    PruebasFM: solo marca el CASO_ID indicado como CONFIRMADA_BAJA."""

    def _df_dos_casos(self):
        return pd.DataFrame([
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': '1', 'VIN': 'V1',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_ESTADO_EXPIRED},
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': '2', 'VIN': 'V2',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC},
        ])[CASOS_BAJA_CM_COLUMNS]

    def test_marca_el_caso_indicado_como_confirmada_baja(self):
        df_resultado = confirmar_baja_caso(self._df_dos_casos(), '1')
        caso = df_resultado[df_resultado['CASO_ID'] == '1'].iloc[0]
        self.assertEqual(caso['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)

    def test_no_modifica_un_caso_distinto(self):
        df_resultado = confirmar_baja_caso(self._df_dos_casos(), '1')
        caso_otro = df_resultado[df_resultado['CASO_ID'] == '2'].iloc[0]
        self.assertEqual(caso_otro['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(caso_otro['ORIGEN_CASO'], ORIGEN_CASO_AUSENCIA_3PC)

    def test_no_muta_el_df_original(self):
        df_original = self._df_dos_casos()
        snapshot = df_original.copy()
        confirmar_baja_caso(df_original, '1')
        pd.testing.assert_frame_equal(df_original, snapshot)

    def test_caso_id_inexistente_no_revienta_ni_modifica_nada(self):
        df_resultado = confirmar_baja_caso(self._df_dos_casos(), '999')
        self.assertTrue((df_resultado['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE).all())


class TestProcesarConfirmacionBajaCmIntegracion(unittest.TestCase):
    """Simula el flujo persistido real (leer -> confirmar -> guardar),
    igual que lo llamaria comercial.py desde Gestionar CM."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "CasosBajaCM.csv")
        df_casos = pd.DataFrame([
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': '1', 'VIN': 'V1',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_ESTADO_EXPIRED},
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': '2', 'VIN': 'V2',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC},
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persiste_la_confirmacion_de_baja(self):
        procesar_confirmacion_baja_cm('1', self.path)
        df_releido = leer_casos_baja_cm(self.path)
        caso = df_releido[df_releido['CASO_ID'] == '1'].iloc[0]
        self.assertEqual(caso['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)

    def test_no_afecta_otro_caso_persistido(self):
        procesar_confirmacion_baja_cm('1', self.path)
        df_releido = leer_casos_baja_cm(self.path)
        caso_otro = df_releido[df_releido['CASO_ID'] == '2'].iloc[0]
        self.assertEqual(caso_otro['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)


class TestConfirmarBajaCasos(unittest.TestCase):
    """Version para varios CASO_ID a la vez de confirmar_baja_caso (ver
    TestConfirmarBajaCaso): usada cuando se selecciona mas de un VIN en
    Gestionar CM. confirmar_baja_caso() sigue intacta y con sus propios
    tests -- esta es una funcion nueva, no un reemplazo."""

    def _df_cinco_casos(self):
        return pd.DataFrame([
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': str(i), 'VIN': f'V{i}',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_ESTADO_EXPIRED}
            for i in range(1, 6)
        ])[CASOS_BAJA_CM_COLUMNS]

    def test_lista_completa_marca_todos_como_confirmada_baja(self):
        df_resultado = confirmar_baja_casos(self._df_cinco_casos(), ['1', '2', '3', '4', '5'])
        self.assertTrue((df_resultado['ESTADO_CASO'] == ESTADO_CASO_CONFIRMADA_BAJA).all())

    def test_lista_parcial_solo_modifica_los_ids_indicados(self):
        df_resultado = confirmar_baja_casos(self._df_cinco_casos(), ['2', '4'])
        estados = dict(zip(df_resultado['CASO_ID'], df_resultado['ESTADO_CASO']))
        self.assertEqual(estados['2'], ESTADO_CASO_CONFIRMADA_BAJA)
        self.assertEqual(estados['4'], ESTADO_CASO_CONFIRMADA_BAJA)

    def test_ids_no_incluidos_permanecen_intactos(self):
        df_resultado = confirmar_baja_casos(self._df_cinco_casos(), ['2', '4'])
        estados = dict(zip(df_resultado['CASO_ID'], df_resultado['ESTADO_CASO']))
        for caso_id in ('1', '3', '5'):
            self.assertEqual(estados[caso_id], ESTADO_CASO_PENDIENTE,
                              f"Fallo: el caso {caso_id} no estaba en la lista y no debía modificarse.")

    def test_lista_vacia_no_modifica_nada(self):
        df_resultado = confirmar_baja_casos(self._df_cinco_casos(), [])
        self.assertTrue((df_resultado['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE).all())

    def test_no_muta_el_df_original(self):
        df_original = self._df_cinco_casos()
        snapshot = df_original.copy()
        confirmar_baja_casos(df_original, ['1', '2'])
        pd.testing.assert_frame_equal(df_original, snapshot)

    def test_ids_inexistentes_no_revientan_ni_modifican_nada(self):
        df_resultado = confirmar_baja_casos(self._df_cinco_casos(), ['999', '888'])
        self.assertTrue((df_resultado['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE).all())


class TestProcesarConfirmacionBajaCmMultipleIntegracion(unittest.TestCase):
    """Simula el flujo persistido real (leer -> confirmar varios -> guardar
    UNA sola vez), igual que lo llamaria comercial.py al confirmar varios
    VIN seleccionados a la vez en Gestionar CM."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "CasosBajaCM.csv")
        df_casos = pd.DataFrame([
            {**{c: '' for c in CASOS_BAJA_CM_COLUMNS}, 'CASO_ID': str(i), 'VIN': f'V{i}',
             'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_ESTADO_EXPIRED}
            for i in range(1, 6)
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persiste_la_confirmacion_de_varios_casos(self):
        procesar_confirmacion_baja_cm_multiple(['1', '3', '5'], self.path)
        df_releido = leer_casos_baja_cm(self.path)
        estados = dict(zip(df_releido['CASO_ID'], df_releido['ESTADO_CASO']))
        self.assertEqual(estados['1'], ESTADO_CASO_CONFIRMADA_BAJA)
        self.assertEqual(estados['3'], ESTADO_CASO_CONFIRMADA_BAJA)
        self.assertEqual(estados['5'], ESTADO_CASO_CONFIRMADA_BAJA)

    def test_no_afecta_los_casos_fuera_de_la_lista(self):
        procesar_confirmacion_baja_cm_multiple(['1', '3', '5'], self.path)
        df_releido = leer_casos_baja_cm(self.path)
        estados = dict(zip(df_releido['CASO_ID'], df_releido['ESTADO_CASO']))
        self.assertEqual(estados['2'], ESTADO_CASO_PENDIENTE)
        self.assertEqual(estados['4'], ESTADO_CASO_PENDIENTE)

    def test_lista_vacia_no_escribe_el_archivo(self):
        """No debe haber escritura innecesaria: con una lista vacia el CSV
        no debe tocarse (se verifica por mtime, ademas de por contenido)."""
        mtime_antes = os.path.getmtime(self.path)
        procesar_confirmacion_baja_cm_multiple([], self.path)
        mtime_despues = os.path.getmtime(self.path)
        self.assertEqual(mtime_antes, mtime_despues, "Fallo: una lista vacia no debia reescribir el CSV.")

        df_releido = leer_casos_baja_cm(self.path)
        self.assertTrue((df_releido['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE).all())


if __name__ == '__main__':
    unittest.main()
