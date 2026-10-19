# Gestor SSCC

Aplicación de escritorio (Windows, PyQt6) que centraliza la gestión de la flota comercial de **Servicios Conectados Chile**: contratos y renovaciones, activaciones y bajas, provisiones financieras, contratos de mantenimiento (CM), facturación manual, contactos, instalaciones y envío de correos. Reemplaza el trabajo manual sobre varios Excel por una sola herramienta con reglas de negocio, historial de cambios y respaldos automáticos.

Proyecto desarrollado como proyecto de título (DUOC UC). Los datos reales de la empresa **no** forman parte de este repositorio: todo lo que se incluye en `duoc/archivos de referencia` y en las pruebas es **ficticio**.

## Qué hace

| Sección | Para qué sirve |
|---|---|
| **Vista General** | Resumen por cliente y por unidad (VIN) de toda la flota. |
| **Comercial** | Bandejas de trabajo del equipo comercial: renovar contratos, recuperar clientes, nuevas oportunidades, oportunidades CM e inconsistencias entre forma de contrato y tipo de facturación. |
| **Operaciones** | Cola de activaciones, unidades sin flota y bajas, cruzada con Servicios Conectados. |
| **Ingresos y Conciliación** | Provisiones, Contratos (CM), Facturación Manual y JustTime. |
| **Administración** | Clientes, contactos, ejecutivos, instalaciones e historial de cambios. |
| **Correos** | Plantillas y envío masivo por Outlook con registro de lo enviado. |
| **Configuración** | Rutas de archivos, respaldos y ajustes. |

## Cómo está construida

- **Fuente de datos:** archivos Excel/CSV compartidos (SharePoint/OneDrive). No hay servidor ni base de datos: la app lee y escribe esos archivos con salvaguardas.
- **Núcleo (`src/core/`):** `DataManager` (carga en memoria), lectores y escritores de Excel/CSV, vigilante de archivos (watchdog), monitor de bloqueos y administrador de respaldos.
- **Servicios (`src/services/`):** reglas de negocio puras (sin interfaz), pensadas para probarse por separado.
- **Interfaz (`src/ui/`):** un módulo por pantalla sobre PyQt6, con tema claro/oscuro (`src/theme/`).
- **Integridad:** respaldos automáticos antes de escribir, escritura atómica, historial de cada cambio (`LogApp.csv`) y papelera de registros eliminados.

El detalle técnico y de negocio está en [`docs/`](../../Evidencias%20de%20documentaci%C3%B3n/docs/README.md) (Vault de Obsidian; también se lee como Markdown normal). Para empezar: [Arquitectura](../../Evidencias%20de%20documentaci%C3%B3n/docs/04.%20Arquitectura%20y%20Patrones%20del%20Sistema.md), [Flujos de datos](../../Evidencias%20de%20documentaci%C3%B3n/docs/05.%20Flujos%20de%20Datos%20y%20Sincronización.md) y [Manual de operación](../../Evidencias%20de%20documentaci%C3%B3n/docs/10.%20Manual%20de%20Operación.md). Los diagramas están en [`diagramas/`](../../Evidencias%20de%20documentaci%C3%B3n/diagramas/).

## Probarla con datos de ejemplo

Requisitos: Windows y Python 3.14 (es la versión con la que se desarrolló).

```bash
pip install -r requirements.txt
python preparar_demo.py     # copia los datos ficticios a datos_demo/ y crea app_config.json
python main.py
```

`preparar_demo.py` trabaja sobre una copia (`datos_demo/`) porque la aplicación modifica los archivos que abre; los originales de `duoc/archivos de referencia` quedan intactos. Para volver al estado inicial: `python preparar_demo.py --forzar`.

Algunas funciones dependen de servicios que no existen en esta versión pública: el envío de correos requiere Outlook de escritorio, y la sincronización de Provisiones, las notas de venta y Power BI requieren los enlaces corporativos, que aquí van vacíos (`app_config.example.json`).

## Pruebas automatizadas

Más de mil pruebas con `unittest` en `src/tests/`. La suite monta un entorno aislado con datos generados (`src/tests/generar_mock_data.py`) y no toca los datos de trabajo:

```bash
python src/tests/test_main.py
```

Ver [Pruebas y auditoría de tests](../../Evidencias%20de%20documentaci%C3%B3n/docs/11.%20Pruebas%20y%20Auditoría%20de%20Tests.md).

## Ejecutable

El ejecutable compilado no forma parte de esta versión publicada. Para generarlo desde el código (PyInstaller, carpeta `Gestor_SSCC`) usa `exe.bat`. Para probar la aplicación usa `preparar_demo.py` (datos ficticios).

## Contenido del repositorio

```
main.py                 punto de entrada
config/                 lectura de app_config.json y catálogo de archivos de datos
src/core, services, ui  núcleo, reglas de negocio e interfaz
src/theme, assets       tema visual, fuentes e imágenes
src/tests               pruebas automatizadas y generador de datos ficticios
(ver ../../Evidencias de documentación/docs)  documentación técnica y funcional
(ver ../../Evidencias de documentación/diagramas)  diagramas de arquitectura y de datos
duoc/calidad            plan de pruebas y gestión de cambios (los usa el auditor de tests)
duoc/archivos de referencia   datos de prueba ficticios con el formato real de los archivos
```

## Privacidad

Se excluyeron del repositorio las rutas corporativas, los enlaces de SharePoint/Power BI y de servicios internos, respaldos, historial y cualquier Excel/CSV con datos de la empresa; el directorio de ejecutivos que trae el código es ficticio. `app_config.json` (rutas de cada equipo) no se versiona: la plantilla es `app_config.example.json`.

## Nota sobre la anonimización

Para su publicación académica se anonimizaron nombres de personas, firmas y datos de contacto, y se generalizó el nombre de la empresa ("Empresa Demo" / "Servicios Conectados"). Los logotipos, fotografías y el icono de la aplicación en `src/assets/` son **marcadores de posición** generados para esta versión; las imágenes originales no se publican. Los datos de `duoc/archivos de referencia` son ficticios.
