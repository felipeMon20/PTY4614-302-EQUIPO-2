import os
import json
import tempfile
import unittest

import pandas as pd

from src.services.contactos_service import (
    normalizar_id_contacto, cargar_favoritos, guardar_favoritos, migrar_favoritos_legacy,
    generar_nuevo_id_contacto, formatear_telefono_chile, aplicar_cambios_pendientes_contactos,
    aplicar_filtro_checkbox, buscar_texto_global, ordenar_por_favoritos_e_id,
)


class TestNormalizarIdContacto(unittest.TestCase):
    """Extraccion literal de ContactosModule._normalize_id(): funcion pura,
    sin PyQt/QThread/DataManager."""

    def test_entero(self):
        self.assertEqual(normalizar_id_contacto(458), "458")

    def test_float_con_punto_cero(self):
        self.assertEqual(normalizar_id_contacto(458.0), "458")

    def test_string_con_punto_cero(self):
        self.assertEqual(normalizar_id_contacto("458.0"), "458")

    def test_string_limpio(self):
        self.assertEqual(normalizar_id_contacto("458"), "458")

    def test_nulo(self):
        self.assertEqual(normalizar_id_contacto(None), "")
        self.assertEqual(normalizar_id_contacto(pd.NA), "")

    def test_no_numerico_se_conserva(self):
        self.assertEqual(normalizar_id_contacto("ABC123"), "ABC123")


class TestFavoritos(unittest.TestCase):
    """Extraccion literal de ContactosModule.load_pinned()/save_pinned():
    I/O de JSON puro, sin PyQt."""

    def test_cargar_favoritos_archivo_inexistente(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cargar_favoritos(os.path.join(tmp, 'no_existe.json')), [])

    def test_guardar_y_cargar_favoritos(self):
        with tempfile.TemporaryDirectory() as tmp:
            filepath = os.path.join(tmp, 'config', 'pinned_contacts.json')
            guardar_favoritos(filepath, ['1', '2', '3'])
            self.assertEqual(cargar_favoritos(filepath), ['1', '2', '3'])

    def test_cargar_favoritos_json_corrupto(self):
        with tempfile.TemporaryDirectory() as tmp:
            filepath = os.path.join(tmp, 'pinned_contacts.json')
            with open(filepath, 'w') as f:
                f.write("{esto no es json valido")
            self.assertEqual(cargar_favoritos(filepath), [])


class TestMigrarFavoritosLegacy(unittest.TestCase):
    """Extraccion literal de la parte de calculo puro de
    ContactosModule._migrate_pinned_contacts()."""

    def setUp(self):
        self.df = pd.DataFrame({
            'ID': ['1', '2'],
            'CDB': ['1001', '1002'],
            'Nombre': ['Juan', 'Ana'],
            'Correo electrónico': ['juan@x.cl', 'ana@x.cl'],
        })

    def test_sin_favoritos_no_migra(self):
        self.assertIsNone(migrar_favoritos_legacy([], self.df))

    def test_tabla_vacia_no_migra(self):
        self.assertIsNone(migrar_favoritos_legacy(['1001_Juan_juan@x.cl'], pd.DataFrame()))

    def test_sin_columna_id_no_migra(self):
        df_sin_id = self.df.drop(columns=['ID'])
        self.assertIsNone(migrar_favoritos_legacy(['1001_Juan_juan@x.cl'], df_sin_id))

    def test_favoritos_ya_migrados_no_hace_nada(self):
        self.assertIsNone(migrar_favoritos_legacy(['1', '2'], self.df))

    def test_migra_clave_compuesta_a_id_fisico(self):
        resultado = migrar_favoritos_legacy(['1001_Juan_juan@x.cl'], self.df)
        self.assertEqual(resultado, ['1'])

    def test_clave_compuesta_sin_match_unico_se_descarta(self):
        resultado = migrar_favoritos_legacy(['9999_Nadie_nadie@x.cl'], self.df)
        self.assertEqual(resultado, [])

    def test_mezcla_ids_nuevos_y_claves_antiguas(self):
        resultado = migrar_favoritos_legacy(['2', '1001_Juan_juan@x.cl'], self.df)
        self.assertEqual(resultado, ['2', '1'])


class TestGenerarNuevoIdContacto(unittest.TestCase):
    """Extraccion literal del calculo de nuevo ID en
    ContactosModule._open_add_dialog()."""

    def test_tabla_vacia(self):
        self.assertEqual(generar_nuevo_id_contacto(pd.DataFrame()), "1")

    def test_sin_columna_id(self):
        self.assertEqual(generar_nuevo_id_contacto(pd.DataFrame({'Nombre': ['Juan']})), "1")

    def test_maximo_mas_uno(self):
        df = pd.DataFrame({'ID': ['1', '5', '3']})
        self.assertEqual(generar_nuevo_id_contacto(df), "6")

    def test_ids_no_numericos_no_rompen(self):
        df = pd.DataFrame({'ID': ['ABC', 'XYZ']})
        self.assertEqual(generar_nuevo_id_contacto(df), "1")


class TestFormatearTelefonoChile(unittest.TestCase):
    """Extraccion y unificacion del formateo de telefono duplicado entre
    ContactosModule.on_item_edited() y
    ContactosAddDialog._validate_and_accept()."""

    def test_once_digitos_con_prefijo_56(self):
        self.assertEqual(formatear_telefono_chile('56912345678'), '+56 9 1234 5678')

    def test_nueve_digitos_empieza_con_9(self):
        self.assertEqual(formatear_telefono_chile('912345678'), '+56 9 1234 5678')

    def test_ocho_digitos(self):
        self.assertEqual(formatear_telefono_chile('12345678'), '+56 9 1234 5678')

    def test_formato_no_reconocido_agrega_signo_mas(self):
        self.assertEqual(formatear_telefono_chile('123'), '+123')

    def test_sin_digitos_devuelve_none(self):
        self.assertIsNone(formatear_telefono_chile(''))
        self.assertIsNone(formatear_telefono_chile('   '))

    def test_ignora_caracteres_no_numericos(self):
        self.assertEqual(formatear_telefono_chile('+56 9 1234 5678'), '+56 9 1234 5678')


class TestAplicarCambiosPendientesContactos(unittest.TestCase):
    """Extraccion y unificacion de la superposicion de pending_changes, antes
    duplicada entre ContactosModule.filter_tables() y
    ContactosModule._on_save_finished()."""

    def test_sin_cambios_no_modifica(self):
        df = pd.DataFrame({'ID': ['1', '2'], 'Nombre': ['Juan', 'Ana']})
        resultado = aplicar_cambios_pendientes_contactos(df, {})
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Juan')

    def test_sin_columna_id_no_modifica(self):
        df = pd.DataFrame({'Nombre': ['Juan']})
        pending = {'1': {'cambios': {'Nombre': 'Pedro'}}}
        resultado = aplicar_cambios_pendientes_contactos(df, pending)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Juan')

    def test_aplica_cambio_por_id(self):
        df = pd.DataFrame({'ID': ['1', '2'], 'Nombre': ['Juan', 'Ana']})
        pending = {'1': {'cambios': {'Nombre': 'Pedro'}}}
        resultado = aplicar_cambios_pendientes_contactos(df, pending)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Pedro')
        self.assertEqual(resultado.iloc[1]['Nombre'], 'Ana')

    def test_id_pendiente_inexistente_se_ignora(self):
        df = pd.DataFrame({'ID': ['1'], 'Nombre': ['Juan']})
        pending = {'999': {'cambios': {'Nombre': 'Pedro'}}}
        resultado = aplicar_cambios_pendientes_contactos(df, pending)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Juan')

    def test_comparacion_ignora_formato_del_id(self):
        # IDs con '.0' residual y claves pendientes en distinto casing deben
        # seguir emparejando (mismo criterio unificado de mayusculas).
        df = pd.DataFrame({'ID': ['1.0'], 'Nombre': ['Juan']})
        pending = {'1': {'cambios': {'Nombre': 'Pedro'}}}
        resultado = aplicar_cambios_pendientes_contactos(df, pending)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Pedro')


class TestAplicarFiltroCheckbox(unittest.TestCase):
    """Extraccion y unificacion del filtro por checkboxes de
    ContactosModule.filter_tables(), duplicado para 'Flota' y 'Nombre'."""

    def setUp(self):
        self.df = pd.DataFrame({'Flota': ['Empresa A', 'Empresa B', 'Empresa C']})

    def test_todos_marcados_no_filtra(self):
        resultado = aplicar_filtro_checkbox(self.df, 'Flota', ['Empresa A', 'Empresa B', 'Empresa C'], True, False)
        self.assertEqual(len(resultado), 3)

    def test_ninguno_marcado_vacia(self):
        resultado = aplicar_filtro_checkbox(self.df, 'Flota', [], False, True)
        self.assertEqual(len(resultado), 0)

    def test_algunos_marcados_filtra(self):
        resultado = aplicar_filtro_checkbox(self.df, 'Flota', ['Empresa A'], False, False)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Flota'], 'Empresa A')


class TestBuscarTextoGlobal(unittest.TestCase):
    """Extraccion y unificacion de la busqueda global multi-columna de
    ContactosModule.filter_tables()."""

    def setUp(self):
        self.df = pd.DataFrame({
            'CDB': ['1001', '1002'],
            'Nombre': ['Juan Perez', 'Ana Soto'],
        })

    def test_texto_vacio_no_filtra(self):
        resultado = buscar_texto_global(self.df, ['CDB', 'Nombre'], '')
        self.assertEqual(len(resultado), 2)

    def test_encuentra_por_termino_parcial(self):
        resultado = buscar_texto_global(self.df, ['CDB', 'Nombre'], 'juan')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Juan Perez')

    def test_palabras_separadas_por_espacio_exigen_todas_and(self):
        # Corregido (25-09-2026): antes cada palabra se combinaba con OR
        # (bug real reportado: buscar una razon social completa devolvia
        # decenas de resultados sin relacion). Ahora "juan soto" exige
        # ambas palabras en la misma fila -- ninguna fila del setUp tiene
        # las dos, asi que no debe encontrar nada.
        resultado = buscar_texto_global(self.df, ['CDB', 'Nombre'], 'juan soto')
        self.assertEqual(len(resultado), 0)

    def test_palabras_separadas_por_espacio_encuentran_la_fila_correcta(self):
        resultado = buscar_texto_global(self.df, ['CDB', 'Nombre'], 'juan perez')
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['Nombre'], 'Juan Perez')

    def test_terminos_separados_por_coma_son_independientes_or(self):
        # Las comas si combinan con OR (mismo contrato que
        # comercial_services.construir_mascara_busqueda): permite pegar
        # listas de VINs/CDB vía MultiSearchLineEdit, que convierte cada
        # salto de linea pegado en una coma.
        resultado = buscar_texto_global(self.df, ['CDB', 'Nombre'], 'juan, soto')
        self.assertEqual(len(resultado), 2)

    def test_columna_ausente_se_ignora(self):
        resultado = buscar_texto_global(self.df, ['Columna Que No Existe', 'Nombre'], 'juan')
        self.assertEqual(len(resultado), 1)


class TestOrdenarPorFavoritosEId(unittest.TestCase):
    """Extraccion literal del paso de ordenamiento (favoritos primero, luego
    ID ascendente) de ContactosModule.filter_tables()."""

    def test_favoritos_primero(self):
        df = pd.DataFrame({'ID': ['1', '2', '3'], 'Nombre': ['Uno', 'Dos', 'Tres']})
        resultado = ordenar_por_favoritos_e_id(df, pinned_contacts=['3'])
        self.assertEqual(resultado.iloc[0]['ID'], '3')

    def test_sin_favoritos_ordena_por_id_ascendente(self):
        df = pd.DataFrame({'ID': ['3', '1', '2'], 'Nombre': ['Tres', 'Uno', 'Dos']})
        resultado = ordenar_por_favoritos_e_id(df, pinned_contacts=[])
        self.assertEqual(list(resultado['ID']), ['1', '2', '3'])

    def test_df_vacio_no_falla(self):
        resultado = ordenar_por_favoritos_e_id(pd.DataFrame(), pinned_contacts=[])
        self.assertTrue(resultado.empty)


if __name__ == '__main__':
    unittest.main()
