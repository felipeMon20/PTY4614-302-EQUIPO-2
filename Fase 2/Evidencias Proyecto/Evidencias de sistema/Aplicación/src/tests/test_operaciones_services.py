import unittest
from datetime import datetime, timedelta

from types import SimpleNamespace

import pandas as pd

from src.core.data_manager import DataManager
from src.services.operaciones_services import (
    filtrar_activaciones, filtrar_sin_flota, filtrar_bajas, armar_export_contactos_ejecutivo,
    calcular_cambios_marcar_desconectado, calcular_cambios_marcar_conectado,
    separar_vins_contrato_abierto, filtrar_cdb_sin_contacto,
)
from src.services.comercial_services import (
    filtrar_gestionar_bajas, filtrar_renovaciones, contratos_actuales, agregar_id_a_cambios,
    aplicar_cambios_pendientes,
)


def _fecha(dias_desde_hoy):
    return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')


def _fila(estado_comercial='VIGENTE', estado_activacion='CONECTADO', etapa_gestion='CLIENTE',
          termino_contrato=None, vin='VIN1', cdb='100', razon_social='Cliente Uno', ejecutivo='Ana'):
    if termino_contrato is None:
        termino_contrato = _fecha(365)
    return {
        'VIN': vin, 'CDB': '99999', 'CDB FLOTA': cdb, 'RAZÓN SOCIAL': razon_social, 'EJECUTIVO': ejecutivo,
        'ESTADO COMERCIAL': estado_comercial, 'ESTADO DE ACTIVACIÓN ACTUAL': estado_activacion,
        'ETAPA GESTIÓN': etapa_gestion, 'TÉRMINO CONTRATO': termino_contrato,
    }


class TestFiltrarActivaciones(unittest.TestCase):
    """Regla vigente (rediseño 24-09-2026, alineado con
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ -- ver constants.py y el
    docstring de filtrar_activaciones): entran las unidades con ESTADO DE
    ACTIVACIÓN ACTUAL en Activando, No entregado o Desconectado (agregado
    24-09-2026, pedido explícito del usuario: antes Vigente+Desconectado y
    Activación Pendiente+Desconectado, con ETAPA GESTIÓN=Operaciones, no
    tenían ninguna cola en Operaciones) Y ETAPA GESTIÓN=Operaciones. La
    segunda condición es la que faltaba antes de este rediseño: sin ella,
    combinaciones que la matriz manda a COMERCIAL (ej. Vencido+Activando)
    igual entraban. Vigente+Activando (antes "Conectividad", pestaña
    eliminada) sigue entrando porque la matriz lo manda a OPERACIONES. SIN
    FLOTA ya no entra aquí: tiene su propia pestaña (ver filtrar_sin_flota)."""

    def test_activando_con_etapa_operaciones_entra(self):
        df = pd.DataFrame([_fila(estado_activacion='Activando', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_activaciones(df)), 1)

    def test_sin_flota_ya_no_entra(self):
        df = pd.DataFrame([_fila(estado_activacion='Sin flota', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_activaciones(df)), 0)

    def test_no_entregado_con_etapa_operaciones_entra(self):
        # No entregado y Sin flota son estados distintos (09-10-2026): No entregado sigue en Activaciones.
        df = pd.DataFrame([_fila(estado_activacion='No entregado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_activaciones(df)), 1)
        self.assertEqual(len(filtrar_sin_flota(df)), 0)

    def test_conectado_no_entra(self):
        df = pd.DataFrame([_fila(estado_activacion='Conectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_activaciones(df)), 0)

    def test_vigente_activando_con_etapa_operaciones_entra(self):
        """Caso que antes vivia en la pestaña "Conectividad" (eliminada,
        24-09-2026): Vigente + Activando sigue entrando a Activaciones
        porque la matriz manda esa combinación a OPERACIONES."""
        df = pd.DataFrame([_fila(estado_comercial='Vigente', estado_activacion='Activando', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_activaciones(df)), 1)

    def test_activando_con_etapa_comercial_no_entra(self):
        """Alineado con la matriz (ej. Vencido+Activando -> COMERCIAL): si
        ETAPA GESTIÓN no es Operaciones, no entra aunque el ESTADO DE
        ACTIVACIÓN ACTUAL sea Activando."""
        df = pd.DataFrame([_fila(estado_comercial='Vencido', estado_activacion='Activando', etapa_gestion='Comercial')])
        self.assertEqual(len(filtrar_activaciones(df)), 0)

    def test_sin_columna_etapa_gestion_retorna_vacio(self):
        df = pd.DataFrame([_fila(estado_activacion='Activando')]).drop(columns=['ETAPA GESTIÓN'])
        self.assertTrue(filtrar_activaciones(df).empty)

    def test_df_vacio_retorna_vacio(self):
        self.assertTrue(filtrar_activaciones(pd.DataFrame()).empty)

    def test_combinacion_mixta(self):
        df = pd.DataFrame([
            _fila(vin='A', estado_activacion='Activando', etapa_gestion='Operaciones'),
            _fila(vin='B', estado_activacion='Sin flota', etapa_gestion='Operaciones'),
            _fila(vin='C', estado_activacion='No entregado', etapa_gestion='Operaciones'),
            _fila(vin='D', estado_activacion='Conectado', etapa_gestion='Operaciones'),
            _fila(vin='E', estado_activacion='Desconectado', etapa_gestion='Operaciones'),
            _fila(vin='F', estado_comercial='Vencido', estado_activacion='Activando', etapa_gestion='Comercial'),
        ])
        resultado = filtrar_activaciones(df)
        self.assertEqual(set(resultado['VIN']), {'A', 'C', 'E'})


class TestFiltrarBajas(unittest.TestCase):
    """Regla confirmada con el usuario (ajustada 22-09-2026): TÉRMINO
    CONTRATO vencido O por vencer (<=30 días, misma regla que Renovaciones
    de Comercial) Y ESTADO DE ACTIVACIÓN ACTUAL = Conectado Y ETAPA GESTIÓN
    = Operaciones -- unidades cuyo contrato ya terminó o está por terminar,
    pero que la app todavía no marcó como desconectadas. Reutiliza
    clasificar_vigencia_contrato (comercial_services) para la fecha, no
    reimplementa el parseo."""

    def test_las_tres_condiciones_entra(self):
        df = pd.DataFrame([_fila(termino_contrato=_fecha(-10), estado_activacion='Conectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_bajas(df)), 1)

    def test_por_vencer_dentro_de_30_dias_entra(self):
        # Ajuste 22-09-2026: antes solo "vencido" entraba; ahora, igual que
        # Renovaciones, "por vencer" (<=30 días) también -- así una unidad
        # recién enviada desde Renovaciones con "Enviar a operaciones" es
        # visible de inmediato en Operaciones, sin esperar a que venza.
        df = pd.DataFrame([_fila(termino_contrato=_fecha(15), estado_activacion='Conectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_bajas(df)), 1)

    def test_contrato_lejos_de_vencer_no_entra(self):
        df = pd.DataFrame([_fila(termino_contrato=_fecha(60), estado_activacion='Conectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_bajas(df)), 0)

    def test_sin_conectado_no_entra(self):
        df = pd.DataFrame([_fila(termino_contrato=_fecha(-10), estado_activacion='Desconectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_bajas(df)), 0)

    def test_sin_etapa_gestion_operaciones_no_entra(self):
        df = pd.DataFrame([_fila(termino_contrato=_fecha(-10), estado_activacion='Conectado', etapa_gestion='Comercial')])
        self.assertEqual(len(filtrar_bajas(df)), 0)

    def test_mensual_nunca_vencido_no_entra(self):
        df = pd.DataFrame([_fila(termino_contrato='MENSUAL', estado_activacion='Conectado', etapa_gestion='Operaciones')])
        self.assertEqual(len(filtrar_bajas(df)), 0)

    def test_df_vacio_retorna_vacio(self):
        self.assertTrue(filtrar_bajas(pd.DataFrame()).empty)


class TestArmarExportContactosEjecutivo(unittest.TestCase):

    def test_agrupa_por_cdb_y_junta_vines(self):
        df_unidades = pd.DataFrame([
            _fila(vin='V1', cdb='100', razon_social='Cliente Uno', ejecutivo='Ana'),
            _fila(vin='V2', cdb='100', razon_social='Cliente Uno', ejecutivo='Ana'),
        ])
        df_contactos = pd.DataFrame([
            {'CDB': '100', 'Nombre': 'Juan', 'Apellidos': 'Soto', 'Correo electrónico': 'juan@x.cl', 'Número móvil': '+56911112222'},
        ])
        resultado = armar_export_contactos_ejecutivo(df_unidades, df_contactos)
        self.assertEqual(len(resultado), 1)
        fila = resultado.iloc[0]
        self.assertEqual(fila['CDB FLOTA'], '100')
        self.assertEqual(set(fila['VINES PENDIENTES'].split(', ')), {'V1', 'V2'})
        self.assertEqual(fila['NOMBRE CONTACTO'], 'Juan')

    def test_cdb_sin_contacto_igual_aparece_con_campos_vacios(self):
        df_unidades = pd.DataFrame([_fila(vin='V1', cdb='999')])
        df_contactos = pd.DataFrame([
            {'CDB': '100', 'Nombre': 'Juan', 'Apellidos': 'Soto', 'Correo electrónico': 'juan@x.cl', 'Número móvil': '1'},
        ])
        resultado = armar_export_contactos_ejecutivo(df_unidades, df_contactos)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['NOMBRE CONTACTO'], '')

    def test_multiples_contactos_mismo_cdb_generan_multiples_filas(self):
        df_unidades = pd.DataFrame([_fila(vin='V1', cdb='100')])
        df_contactos = pd.DataFrame([
            {'CDB': '100', 'Nombre': 'Juan', 'Apellidos': 'Soto', 'Correo electrónico': 'juan@x.cl', 'Número móvil': '1'},
            {'CDB': '100', 'Nombre': 'Maria', 'Apellidos': 'Perez', 'Correo electrónico': 'maria@x.cl', 'Número móvil': '2'},
        ])
        resultado = armar_export_contactos_ejecutivo(df_unidades, df_contactos)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(set(resultado['NOMBRE CONTACTO']), {'Juan', 'Maria'})

    def test_df_unidades_vacio_retorna_vacio(self):
        resultado = armar_export_contactos_ejecutivo(pd.DataFrame(), pd.DataFrame())
        self.assertTrue(resultado.empty)


class TestCalcularCambiosMarcarDesconectado(unittest.TestCase):
    """"Marcar como DESCONECTADO" (Operaciones -> Bajas, cierre del ciclo
    Comercial -> Operaciones -> Comercial para BAJA). La función es pura y
    no decide elegibilidad (ver _obtener_vins_baja_seleccionados en
    operaciones.py, que filtra por ESTADO COMERCIAL == 'BAJA' exacto antes
    de llegar acá): estos tests solo verifican el cálculo en sí, incluida
    su reutilización de la matriz existente."""

    def test_baja_pasa_a_desconectado(self):
        fila = _fila(estado_comercial='Baja', estado_activacion='Conectado', etapa_gestion='Operaciones')
        cambios = calcular_cambios_marcar_desconectado(fila)
        self.assertEqual(cambios['ESTADO DE ACTIVACIÓN ACTUAL'], 'DESCONECTADO')

    def test_etapa_gestion_recalculada_con_matriz_existente(self):
        # BAJA + DESCONECTADO -> COMERCIAL, según
        # ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ (constants.py): mismo
        # resultado que se obtiene llamando directo a
        # DataFrameFormatter.calcular_etapa_gestion_esperada, sin una
        # segunda regla en esta función.
        fila = _fila(estado_comercial='Baja', estado_activacion='Conectado', etapa_gestion='Operaciones')
        cambios = calcular_cambios_marcar_desconectado(fila)
        self.assertEqual(cambios['ETAPA GESTIÓN'], 'COMERCIAL')

    def test_baja_conserva_su_estado_comercial(self):
        # Desde el 23-09-2026 el cambio siempre incluye ESTADO COMERCIAL: solo
        # BAJA SOLICITADA se promueve a BAJA; una unidad ya en BAJA queda igual.
        fila = _fila(estado_comercial='Baja', estado_activacion='Activando', etapa_gestion='Operaciones')
        cambios = calcular_cambios_marcar_desconectado(fila)
        self.assertEqual(cambios['ESTADO COMERCIAL'], 'Baja')

    def test_no_discrimina_por_si_sola_baja_solicitada(self):
        # La función en sí no filtra por ESTADO COMERCIAL -- la exclusión de
        # BAJA SOLICITADA es responsabilidad de quien arma la selección
        # (operaciones.py._obtener_vins_baja_seleccionados, que usa
        # filtrar_gestionar_bajas antes de llegar acá). Este test documenta
        # ese contrato: si se le pasara una fila BAJA SOLICITADA por error,
        # igual calcularía el resultado de la matriz para ese estado (que no
        # es COMERCIAL, ver test de abajo), no una excepción silenciosa.
        fila = _fila(estado_comercial='Baja Solicitada', estado_activacion='Conectado', etapa_gestion='Operaciones')
        cambios = calcular_cambios_marcar_desconectado(fila)
        self.assertEqual(cambios['ETAPA GESTIÓN'], 'COMERCIAL')


class TestCicloBajaOperacionesComercial(unittest.TestCase):
    """Composición end-to-end (sin PyQt6) del cierre de ciclo: aplica
    calcular_cambios_marcar_desconectado() sobre una fila que hoy está en
    Operaciones -> Bajas y verifica, reutilizando los filtros reales (sin
    reimplementarlos), que sale de esa cola y sigue en Comercial ->
    Gestionar Bajas."""

    def test_unidad_sale_de_bajas_y_sigue_en_gestionar_bajas(self):
        fila_antes = _fila(
            estado_comercial='Baja', estado_activacion='Conectado', etapa_gestion='Operaciones',
            termino_contrato=_fecha(-10), vin='V1',
        )
        df_antes = pd.DataFrame([fila_antes])
        self.assertEqual(len(filtrar_bajas(df_antes)), 1, "Precondición: la unidad debe partir en Operaciones -> Bajas.")

        cambios = calcular_cambios_marcar_desconectado(fila_antes)
        fila_despues = {**fila_antes, **cambios}
        df_despues = pd.DataFrame([fila_despues])

        self.assertTrue(filtrar_bajas(df_despues).empty, "La unidad debe desaparecer de Operaciones -> Bajas.")
        self.assertEqual(len(filtrar_gestionar_bajas(df_despues)), 1, "La unidad debe seguir en Comercial -> Gestionar Bajas.")
        self.assertEqual(fila_despues['ESTADO COMERCIAL'], 'Baja', "ESTADO COMERCIAL no debe modificarse.")

    def test_enviar_a_operaciones_desde_renovaciones_por_vencer_entra_a_bajas(self):
        # Regresión (22-09-2026): "Enviar a operaciones" (comercial.py) se
        # usa típicamente sobre unidades de Renovaciones cuyo contrato
        # todavía NO venció (solo "por vencer", <=30 días -- ver
        # filtrar_renovaciones/es_renovacion). Antes del ajuste a
        # filtrar_bajas, ESTADO COMERCIAL/ETAPA GESTIÓN quedaban bien
        # actualizados y la unidad aparecía en Gestionar Bajas, pero NO en
        # Operaciones -> Bajas hasta que el contrato vencía de verdad.
        fila_antes = _fila(
            estado_comercial='Vigente', estado_activacion='Conectado', etapa_gestion='Comercial',
            termino_contrato=_fecha(15), vin='V3',
        )
        df_antes = pd.DataFrame([fila_antes])
        self.assertEqual(len(filtrar_renovaciones(df_antes)), 1, "Precondición: debe partir en Renovaciones.")

        # Mismos cambios forzados que _on_accion_enviar_operaciones_clicked.
        fila_despues = {
            **fila_antes,
            'ESTADO COMERCIAL': 'Baja',
            'ETAPA GESTIÓN': 'Operaciones',
        }
        df_despues = pd.DataFrame([fila_despues])

        # Desde el 08-10-2026 una baja Conectada la gestiona Operaciones y deja de verse en Comercial.
        self.assertEqual(len(filtrar_gestionar_bajas(df_despues)), 0, "Una baja Conectada ya no se ve en Comercial -> Recuperar clientes.")
        self.assertEqual(len(filtrar_bajas(df_despues)), 1, "Debe verse de inmediato en Operaciones -> Bajas, sin esperar a que venza el contrato.")


class TestOperacionesPorContrato(unittest.TestCase):
    """Fase 2 (contratos por ID): Operaciones trabaja sobre el contrato
    actual de cada VIN y guarda por ID."""

    @staticmethod
    def _df_dos_contratos():
        antiguo = {**_fila(estado_comercial='Baja', estado_activacion='Conectado', etapa_gestion='Operaciones',
                           termino_contrato=_fecha(-30), vin='V1', cdb='500'), 'ID': '5'}
        actual = {**_fila(estado_comercial='Activación Pendiente', estado_activacion='Activando',
                          etapa_gestion='Operaciones', termino_contrato='-', vin='V1', cdb='500'), 'ID': '6'}
        otro = {**_fila(vin='V2', cdb='700'), 'ID': '7'}
        return pd.DataFrame([antiguo, actual, otro])

    def test_colas_ven_solo_el_contrato_actual(self):
        df = self._df_dos_contratos()
        self.assertEqual(len(filtrar_bajas(df)), 1, "Precondición: sin filtrar, el contrato antiguo aparece en Bajas.")
        actuales = contratos_actuales(df)
        self.assertEqual(len(actuales), 2)
        self.assertTrue(filtrar_bajas(actuales).empty)
        self.assertEqual(filtrar_activaciones(actuales)['ID'].tolist(), ['6'])

    def test_contratos_actuales_df_del_data_manager(self):
        falso_dm = SimpleNamespace(df_master=self._df_dos_contratos())
        actuales = DataManager.get_contratos_actuales_df(falso_dm)
        self.assertEqual(sorted(actuales['ID'].tolist()), ['6', '7'])
        self.assertEqual(len(falso_dm.df_master), 3, "No debe modificar df_master.")

    def test_conectar_modifica_solo_el_contrato_actual(self):
        df = self._df_dos_contratos()
        actuales = contratos_actuales(df)
        fila = actuales[actuales['VIN'] == 'V1'].iloc[0].to_dict()
        cambios = {'V1': {'VIN': 'V1', 'cambios': calcular_cambios_marcar_conectado(fila)}}
        agregar_id_a_cambios(cambios, actuales)
        self.assertEqual(cambios['V1']['ID'], '6')
        aplicar_cambios_pendientes(df, cambios)
        nuevo = df[df['ID'] == '6'].iloc[0]
        antiguo = df[df['ID'] == '5'].iloc[0]
        self.assertEqual((nuevo['ESTADO COMERCIAL'].upper(), nuevo['ESTADO DE ACTIVACIÓN ACTUAL'].upper()), ('VIGENTE', 'CONECTADO'))
        self.assertEqual((antiguo['ESTADO COMERCIAL'].upper(), antiguo['ESTADO DE ACTIVACIÓN ACTUAL'].upper()), ('BAJA', 'CONECTADO'))

    def test_desconectar_baja_solicitada_modifica_solo_su_contrato(self):
        df = self._df_dos_contratos()
        df.loc[df['ID'] == '6', ['ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL']] = ['Baja Solicitada', 'Conectado']
        df.loc[df['ID'] == '5', 'ESTADO DE ACTIVACIÓN ACTUAL'] = 'Desconectado'
        actuales = contratos_actuales(df)
        fila = actuales[actuales['VIN'] == 'V1'].iloc[0].to_dict()
        cambios = {'V1': {'VIN': 'V1', 'cambios': calcular_cambios_marcar_desconectado(fila)}}
        agregar_id_a_cambios(cambios, actuales)
        aplicar_cambios_pendientes(df, cambios)
        cerrado = df[df['ID'] == '6'].iloc[0]
        self.assertEqual((cerrado['ESTADO COMERCIAL'].upper(), cerrado['ESTADO DE ACTIVACIÓN ACTUAL'].upper()), ('BAJA', 'DESCONECTADO'))
        self.assertEqual(cambios['V1']['ID'], '6')
        self.assertEqual(df[df['ID'] == '5'].iloc[0]['ESTADO DE ACTIVACIÓN ACTUAL'], 'Desconectado')

    def test_separa_contratos_abiertos_de_los_finalizados(self):
        cola = pd.DataFrame([
            _fila(estado_comercial='Baja', vin='V1'),
            _fila(estado_comercial='Baja Solicitada', vin='V2'),
            _fila(estado_comercial='Vigente', vin='V3'),
        ])
        abiertos, cerrados = separar_vins_contrato_abierto(cola, ['v1', 'V2', 'V3'])
        self.assertEqual(abiertos, ['V3'])
        self.assertEqual(cerrados, ['v1', 'V2'])
        self.assertEqual(separar_vins_contrato_abierto(pd.DataFrame(), ['V9']), (['V9'], []))

    def test_contactos_cuenta_cada_unidad_una_vez(self):
        df = self._df_dos_contratos()
        sin_contactos = pd.DataFrame({'CDB': ['999']})
        completo = filtrar_cdb_sin_contacto(df, sin_contactos)
        actual = filtrar_cdb_sin_contacto(contratos_actuales(df), sin_contactos)
        self.assertEqual(completo.set_index('CDB FLOTA').loc['500', 'UNIDADES'], 2)
        self.assertEqual(actual.set_index('CDB FLOTA').loc['500', 'UNIDADES'], 1)


if __name__ == '__main__':
    unittest.main()
