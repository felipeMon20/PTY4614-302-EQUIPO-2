> **Documento histórico (movido a `docs/` el 13-10-2026).** Es la primera descripción de la arquitectura (29-08-2026) y está parcialmente desactualizado (por ejemplo, el archivo maestro hoy es `RM_JAVI.csv` y no un `.xlsx`). Ante cualquier diferencia prevalecen los demás documentos de este Vault, ver [[04. Arquitectura y Patrones del Sistema]].

# Arquitectura del Sistema - Volvo Dashboard 29/08/2026 (desde el 08-10-2026 la aplicación se llama Gestor SSCC)

## 1. Visión General del Proyecto
El **Volvo Dashboard** es una aplicación de escritorio nativa desarrollada en Python (PyQt6) diseñada para centralizar, visualizar y gestionar grandes volúmenes de datos operativos y financieros hecho por Felipe Monsalve Umanzor de Duoc UC.

La arquitectura del sistema está fuertemente inspirada en el patrón **MVC (Modelo-Vista-Controlador)**, desacoplando la lógica de procesamiento de datos (Pandas/Asincronismo) de la capa de presentación visual. Dada la restricción de infraestructura que prohíbe el uso de bases de datos relacionales (SQL), el sistema utiliza archivos Excel (`.xlsx`) como origen maestro de datos (Single Source of Truth), operando mediante procesos ETL (Extracción, Transformación y Carga) en segundo plano.

---

## 2. Estructura Raíz y Configuración

La raíz del proyecto actúa como el punto de entrada y gestor del entorno.

*   `main.py`: Punto de entrada principal de la aplicación de escritorio.
    *   **Carga de Estilos Globales (`load_stylesheet`):** Inicializa la instancia global de `QApplication` y carga la hoja de estilos unificada (`src/assets/styles.qss`), asegurando que la tipografía y los componentes nativos hereden la línea gráfica corporativa desde el inicio.
    *   **Interfaz de Precarga Flotante (`CustomSplashScreen`):** Elimina los bordes de la ventana del sistema operativo (`FramelessWindowHint`), habilita la transparencia de fondo (`WA_TranslucentBackground`) y aplica un efecto de sombra vectorial (`QGraphicsDropShadowEffect`) para generar una tarjeta flotante de estética *premium* sobre el escritorio.
    *   **Control de Precarga (`QTimer`):** Gestiona una barra de progreso basada en temporización. Durante la precarga crea la ventana principal (`MainWindow`) de forma oculta, reduciendo la latencia visual antes de la presentación final al usuario.
*   `app_config.json`: Archivo de persistencia local. Almacena las rutas dinámicas de los archivos maestros y los enlaces externos configurados para la aplicación.
*   `requirements.txt`: Manifiesto de dependencias de Python (Pandas, PyQt6, openpyxl, psutil, matplotlib y otras librerías utilizadas por el proyecto) necesarias para el despliegue del entorno.

### Directorios Estructurales
*   **/config/**
    *   `settings.py`: Script responsable de leer `app_config.json` e inicializar las variables de entorno y rutas maestras para que estén disponibles globalmente en todo el software.
*   **/data/**
    *   Actúa como el espacio de trabajo temporal y de seguridad del sistema.
    *   `/backups/`: Directorio autogestionado por `ExcelWriter`. Almacena copias de seguridad incrementales creadas automáticamente antes de las operaciones de escritura, actualización o eliminación.
    *   `/temp/`: Carpeta para alojar copias temporales utilizadas durante operaciones de lectura/escritura y archivos descargados o preparados para procesamiento.
*   **/logs/**
    *   Almacena los archivos de texto plano (ej. `sistema.log`). Utilizado por el módulo `logging` para trazar el flujo de ejecución y capturar excepciones en tiempo real. La interfaz de Configuración utiliza esta información para mostrar el estado de salud y los errores recientes.

---

## 3. Configuración y Entorno de Ejecución (`config/` y Raíz)

La gestión de variables de entorno, rutas de archivos y enlaces externos se maneja mediante un sistema desacoplado, permitiendo que la aplicación se distribuya a múltiples usuarios sin requerir modificaciones directas en el código fuente.

### `app_config.json` (Directorio Raíz)
Este archivo opera como la capa de persistencia dinámica para las rutas de los repositorios de datos y enlaces externos.
*   **Almacenamiento Estructural:** Guarda las rutas absolutas hacia los archivos maestros, además de las direcciones web utilizadas por los procesos de sincronización y visualización.
*   **Portabilidad:** La externalización de estas rutas previene que queden codificadas rígidamente (*hardcoded*) en la lógica de negocio, facilitando la adaptación de la herramienta a la estructura de directorios particular de cada máquina o perfil de usuario.
*   **Configuración actual:** Entre las claves utilizadas por la aplicación se encuentran `EXCEL_PATH`, `LOG_EXCEL_PATH`, `DELETED_LOG_EXCEL_PATH`, `PROVISION_EXCEL_PATH`, `INSTALACIONES_PATH`, `RM_JAVI_PATH`, `POWERBI_EXCEL_PATH`, `CONTACTOS_EXCEL_PATH`, `CORREOS_EXCEL_PATH`, `PROVISIONES_SHAREPOINT_URL`, `REPORTE_NOTAS_VENTAS_URL` y `POWERBI_EMBED_URL`. (`CUSTOMER_EXCEL_PATH` fue eliminada el 02-09-2026 junto con `direcciones.xlsx`.)

### `config/settings.py`
Es el módulo central encargado de actuar como puente entre la persistencia (`app_config.json`) y el resto del software.
*   **Resolución Dinámica de Entorno:** Identifica si la aplicación se está ejecutando desde un entorno de desarrollo o como un binario compilado (`.exe`). Con base en esto, ajusta el directorio raíz (`BASE_DIR`) para garantizar la correcta localización del archivo de configuración.
*   **Tolerancia a Fallos e Inicialización:** Implementa la rutina `load_config()`, la cual intercepta la ausencia del archivo JSON. Si no existe, crea automáticamente una configuración inicial basada en `DEFAULT_CONFIG`.
*   **Compatibilidad de Configuraciones:** Al cargar una configuración existente, verifica que las claves definidas en `DEFAULT_CONFIG` estén presentes y agrega las faltantes con valores vacíos, permitiendo compatibilidad con configuraciones anteriores.
*   **Gestión de Mutabilidad:** Provee el método `save_config()` para persistir las modificaciones realizadas por el usuario desde el panel de Configuración de la interfaz gráfica.
*   **Exposición de Variables:** Tras la lectura del archivo, expone las rutas y enlaces como variables globales (`EXCEL_PATH`, `PROVISION_EXCEL_PATH`, `POWERBI_EXCEL_PATH`, `CONTACTOS_EXCEL_PATH`, `REPORTE_NOTAS_VENTAS_URL`, `POWERBI_EMBED_URL`, etc.) y calcula paramétricamente el directorio de monitoreo (`WATCH_DIR`). Estos parámetros son consumidos por los motores de lectura, escritura, sincronización, monitoreo y visualización.

---

## 4. El Motor de Datos y Lógica de Negocio (`src/core/`)

El núcleo del sistema está diseñado para procesar operaciones I/O (lectura/escritura de archivos locales y de red) de manera eficiente, garantizando que la Interfaz Gráfica de Usuario (GUI) no ejecute directamente las operaciones pesadas en el hilo principal y manteniendo mecanismos de seguridad para las escrituras.

### 4.1. Asincronismo y Concurrencia (`data_manager.py`)
Actúa como el orquestador principal de la memoria de la aplicación, implementando el patrón de diseño **Singleton** para asegurar que exista una única instancia de los datos compartida entre los módulos.
*   **Hilos de Procesamiento (`QThread`):** Delega la carga de archivos pesados a hilos en segundo plano (`MainDataLoaderThread`, `ProvisionesLoaderThread`, `ContactosLoaderThread`).
*   **Seguridad de Concurrencia e Inyección en RAM:** Administra banderas lógicas (`is_loading_main`, `is_loading_prov`, `is_loading_contactos`) para impedir cargas superpuestas. Mantiene `df_master`, `df_prov`, `df_contactos`, `df_logs` y `df_deleted` en memoria, permitiendo que los módulos trabajen sobre una representación centralizada de los datos.
*   **Señales de Sincronización:** Expone señales como `data_ready`, `provisiones_ready`, `contactos_ready`, `load_error`, `load_provisiones_error` y `load_contactos_error` para comunicar cambios entre los procesos de carga y la interfaz.
*   **Cálculo Financiero Integrado:** El hilo de provisiones extrae las variables `UF` y `CIV`, procesa los planes y calcula valores como `Monto Provisionado`, `Valor Plan` y `VAR` antes de entregar la información a la interfaz.
*   **Métricas de Salud:** Recolecta consumo de RAM mediante `psutil`, tiempos de carga, cantidad de filas en memoria, fecha de modificación del Excel, cantidad de backups y estado de los logs para alimentar el panel de diagnóstico.

### 4.2. Extracción y Preprocesamiento (ETL)
*   **`dataframe_formatter.py`:** Es la capa de preprocesamiento estricto. Implementa un escudo protector (`_validate_columns`) que valida la existencia de columnas primarias (`VIN`, `CHASIS`) y aborta la carga si la estructura mínima no es válida. Normaliza identificadores, limpia valores vacíos, estandariza fechas y recalcula matemáticamente `TÉRMINO CONTRATO` utilizando `INICIO CONTRATO` y `DURACIÓN (MESES)`. Todo este proceso es trazado mediante `logging` hacia `logs/sistema.log`.
*   **`excel_reader.py`:** Utiliza Pandas para leer el archivo maestro y expone métodos específicos (`get_commercial_data`, `get_general_data`, `get_operaciones_data`, `get_logs_data`, `get_deleted_logs_data`) que filtran y entregan únicamente las columnas requeridas por cada contexto. Además, genera y compara un snapshot binario (`.snapshot_comercial.pkl`) para detectar altas, bajas y modificaciones de la base comercial.

### 4.3. Transaccionalidad Segura y Auditoría (`excel_writer.py`)
Dado que no se utiliza SQL, las operaciones CRUD (Crear, Leer, Actualizar, Borrar) se manejan sobre archivos Excel mediante `openpyxl` y Pandas.
*   **Fijación de Hoja Maestra (`_get_active_sheet`):** Cuando el archivo contiene la pestaña `"BBDD (2)"`, el escritor la utiliza como hoja principal; de lo contrario, utiliza la hoja activa.
*   **Comunicación con el Watchdog:** Antes de modificar el archivo, el escritor establece `dm.is_app_saving = True` y registra el tiempo exacto en `dm.save_timestamp`. Esto permite que el observador distinga una modificación originada por la aplicación de una modificación externa.
*   **Backups Preventivos (`_crear_backup`):** Antes de ejecutar operaciones de escritura, actualización o eliminación, el sistema crea automáticamente una copia de seguridad en `/data/backups/`. Para cada archivo mantiene como máximo los últimos 10 backups.
*   **Escritura mediante Archivos Temporales:** Las operaciones se realizan sobre una copia temporal ubicada en `/data/temp/`; una vez finalizada y guardada la operación, la copia temporal reemplaza el archivo objetivo. Se utiliza `fsync` cuando es posible antes de copiar el resultado.
*   **Trazabilidad Diferencial:** Las modificaciones de celdas registran fecha, módulo, identificador, campo modificado, valor anterior y nuevo valor en `LogApp.xlsx`. Las filas eliminadas se almacenan en `RegistroEliminado.xlsx` para conservar trazabilidad y permitir su consulta posterior.

### 4.4. Integración y Monitoreo Continuo
*   **`file_watcher.py` (Observador del Sistema):** Implementa un vigía de archivos en segundo plano utilizando `watchdog`. Incorpora un freno de eventos repetidos de 5 segundos y un silenciador de 10 segundos asociado a `dm.is_app_saving`, evitando recargas provocadas por la propia aplicación.
*   **`sharepoint_sync.py` (Sincronización de Provisiones):** Implementa un trabajador (`SharePointSyncWorker`) que procesa el reporte externo de provisiones. Lee la hoja del año en curso (o la más reciente si aún no existe), identifica registros nuevos mediante `VIN`, evita duplicados y agrega los contratos faltantes al archivo de provisiones preservando las fórmulas relativas mediante `openpyxl` y `Translator`.
*   **`constants.py`:** Centraliza nombres de columnas, estados y mapas semánticos utilizados transversalmente por los módulos, reduciendo la dependencia de textos repetidos y facilitando cambios estructurales en los reportes.

---

## 5. Diseño y Jerarquía Visual (`src/theme/`)

El sistema emplea un patrón de diseño desacoplado para la Interfaz de Usuario (UI). En lugar de concentrar toda la apariencia en cada vista, el diseño se abstrae mediante una paleta, tipografías, hojas QSS y un gestor de estilos reutilizable.

### 5.1. Estandarización Gráfica
*   **`colors.py`:** Define la paleta semántica de la aplicación corporativa mediante códigos hexadecimales. Parametriza colores estructurales (fondos, superficies, bordes) y códigos de estado transaccional (Éxito, Peligro, Advertencia).
*   **`fonts.py`:** Garantiza la coherencia tipográfica a través del sistema mediante objetos `QFont` estandarizados para títulos y textos.
*   **`src/assets/styles.qss`:** Actúa como hoja de estilos global de Qt. Define los estilos reutilizables de botones, tarjetas, barras de búsqueda, tablas y otros componentes visuales.

### 5.2. El Gestor de Estilos
*   **`theme_manager.py`:** Es la clase orquestadora del front-end. Provee métodos reutilizables como `apply_card_style`, `apply_primary_button`, `apply_success_button`, `apply_danger_button`, `apply_secondary_button`, `apply_search_bar`, `apply_combo_box`, `style_title` y `style_subtitle`, permitiendo que los módulos de `src/ui/` apliquen una apariencia coherente sin repetir la lógica de estilos.

---

## 6. Módulos de la Interfaz de Usuario (`src/ui/`)

La capa de presentación visual está estructurada mediante widgets modulares de PyQt6, desacoplando las distintas líneas de negocio de la aplicación en pantallas independientes e interconectadas.

### 6.1. Módulo Directivo (`dashboard.py`)
Diseñado para presentar el dashboard corporativo externo.
*   **Visualización Integrada de Power BI:** Utiliza `QWebEngineView` para cargar la URL de inserción (`POWERBI_EMBED_URL`) configurada en `settings.py`.
*   **Recarga del Reporte:** Incluye un botón que vuelve a cargar la URL del reporte cuando el usuario requiere actualizar la vista.
*   **Manejo de Configuración Ausente:** Si no existe una URL válida, muestra una pantalla informativa solicitando configurar el enlace desde el módulo de Configuración.

### 6.2. Diálogo de Ingreso de Registros (`add_record_dialog.py`)
Componente modal transaccional (`QDialog`) para altas de nuevos vehículos.
*   **Autocompletado Inteligente y Slicing:** Al capturar el identificador `VIN`, calcula automáticamente los últimos 7 caracteres para utilizarlos como `CHASIS`.
*   **Razón Social manual (desde 02-09-2026):** `RAZÓN SOCIAL` es un campo de texto libre del formulario. Antes solo podía completarse mediante una búsqueda automática contra el reporte de Notas de Venta (`_search_in_notas_venta`), que fue eliminada al migrar ese reporte a Power BI.
*   **Matemática en Vivo:** Valida fechas de inicio y utiliza `relativedelta` para proyectar la fecha de `TÉRMINO CONTRATO` cuando corresponde.
*   **Inyección Automática de Estado:** Al aceptar el formulario, incorpora información derivada como el `PERIODO INTERNO` según el periodo actual.

### 6.3. Módulo Comercial y Sincronización Maestra (`comercial.py`)
Es el centro operativo principal para el seguimiento comercial.
*   **Arquitectura No Bloqueante:** Desacopla las transacciones CRUD hacia hilos en segundo plano (`AddRowThread`, `DeleteRowThread`, `SaveExcelThread`), protegiendo el hilo principal de renderizado durante las escrituras.
*   **Espejo Inteligente e Hilo de Fusión (`RMJaviSyncWorker`):** Ejecuta un proceso en segundo plano para leer el archivo `RM_JAVI` y fusionar la información necesaria con la base comercial, utilizando copias temporales y mecanismos de respaldo.
*   **Filtros Avanzados y Menús Persistentes (`KeepOpenMenu`):** Integra filtrado paramétrico por estados, industrias, periodos y ejecutivos, además de controles para seleccionar y ajustar columnas de la tabla.
*   **Acceso a Reporte de Notas de Venta (actualizado 02-09-2026):** Un botón circular amarillo ("BI") abre el enlace externo configurado mediante `REPORTE_NOTAS_VENTAS_URL` para consulta manual en Power BI. Ya no existe autocompletado automático (`_completar_vin_nv`/"Autocompletar VIN"): fue retirado en vez de adaptarlo al nuevo formato del reporte.

### 6.4. Configuración y Monitoreo de Salud (`configuracion.py`)
Panel de administración técnica y parametrización del software.
*   **Centro de Telemetría:** Construye un panel de salud consultando consumo de RAM, tiempos de carga, cantidad de filas, última modificación del Excel y disponibilidad de backups.
*   **Consola de Diagnóstico de Errores:** Permite consultar el historial de errores almacenado en `sistema.log` y realizar acciones de limpieza de la bitácora.
*   **Gestor de Rutas:** Permite inspeccionar y modificar las rutas almacenadas en `app_config.json` y guardar los cambios de configuración.
*   **Herramientas de Mantenimiento:** Incluye acciones para respaldar y restaurar información cuando corresponde según las opciones disponibles del sistema.

### 6.5. Directorio de Contactos (`contactos.py`)
Módulo especializado de consulta, gestión CRUD y sincronización de directorios.
*   **Sincronización con Directorio Externo:** Mediante `PowerBiSyncWorker`, lee el archivo de datos de clientes configurado, filtra los registros que coinciden con los `CDB` de la flota activa y genera/actualiza el directorio local de empresas.
*   **Identidad Física Permanente:** La tabla de contactos exige la columna `ID`, valida que no existan IDs vacíos o duplicados y utiliza ese identificador físico como llave para las operaciones de edición y eliminación.
*   **CRUD Asíncrono:** Las operaciones de guardar, agregar y eliminar contactos se ejecutan mediante `SaveContactosThread`, `AddContactoThread` y `DeleteContactoThread`.
*   **Favoritos Persistentes:** Permite marcar contactos como favoritos y almacena sus identificadores en `config/pinned_contacts.json`.
*   **Filtrado y Ordenamiento:** Aplica búsqueda sobre campos relevantes, prioriza contactos favoritos y mantiene el orden por ID para preservar la identidad de los registros.

### 6.6. Módulo de Contratos de Mantenimiento (`contratos.py`)
Módulo diseñado para gestionar y controlar información de contratos de mantenimiento.
*   **Importación Masiva de Excel (`btn_importar`):** Permite cargar un reporte externo de contratos y comparar la información por VIN para preparar actualizaciones sobre la base comercial.
*   **Arquitectura No Bloqueante:** Utiliza `QThread` y un `QStackedWidget` para realizar procesos de carga y guardado sin bloquear visualmente la ventana.
*   **KPIs Interactivos:** Presenta indicadores de total de contratos, contratos activos, vencidos y monto total de `PAGO CM`, permitiendo filtrar la tabla mediante dichos indicadores.
*   **Formateador Condicional Transaccional:** Valida y transforma en vivo el campo `PAGO CM`, mostrando formatos monetarios y evitando entradas inválidas.

### 6.7. El Motor Tabular Reutilizable (`custom_table.py`)
El componente visual central para la presentación y edición de datos tabulares.
*   **Arquitectura Modelo-Vista (`PandasTableModel`):** Desacopla el DataFrame del componente gráfico `QTableView` y permite representar datos de Pandas dentro de Qt.
*   **Edición y Delegados:** Gestiona edición de celdas y controles desplegables mediante `ComboBoxDelegate` y señales de edición.
*   **Menús Contextuales e Interactividad:** Habilita acciones de cabecera, copia de información y funcionalidades de tabla mediante menús contextuales y atajos.
*   **Herramientas de Exportación:** Incluye funcionalidades para exportar las vistas a Excel y PDF, utilizando `openpyxl` y las herramientas de impresión de Qt.

### 6.8. Vista General y Centro de Mando Híbrido (`general.py`)
Módulo inicial que unifica el control operativo y financiero.
*   **Fuentes de Datos Múltiples:** Utiliza controles de selección para alternar la información comercial y de provisiones dentro de una misma vista.
*   **Paginación y Filtrado:** Presenta los datos de forma controlada, aplicando filtros y ordenamientos según el contexto seleccionado.
*   **Bandeja de Atención Prioritaria:** Calcula una prioridad operacional para ordenar los registros que requieren mayor atención.
*   **Indicadores Financieros:** En el contexto de provisiones, utiliza `VAR` y otros campos financieros para diferenciar visualmente desviaciones.

### 6.9. Auditoría y Papelera de Registros (`historial.py`)
Módulo dedicado a la transparencia y trazabilidad histórica de la aplicación.
*   **Paginación Optimizada:** Divide la visualización de modificaciones y papelera en lotes de 200 filas para evitar cargar grandes volúmenes de registros de una sola vez.
*   **Filtrado Cronológico Inteligente (`filtrar_por_rango`):** Permite consultar auditorías por rangos temporales como hoy, últimos 7 días u otros periodos disponibles.
*   **Destrucción y Vaciado de Logs:** Incluye funciones administrativas para limpiar los libros de auditoría cuando corresponde.

### 6.10. Automatización de Instalaciones y Cruce Maestro (`instalaciones.py`)
Módulo diseñado para optimizar los reportes mensuales de operaciones.
*   **Proceso ETL Asíncrono (`InstalacionesSyncWorker`):** Procesa reportes de instalaciones, cruza información utilizando identificadores de chasis y complementa los registros con información del directorio de empresas.
*   **Gestor de Hojas de Excel:** Además de actualizar el archivo de instalaciones, permite gestionar las hojas históricas mediante acciones de renombrado y eliminación.

### 6.11. Módulo de Correo Masivo y Cruce CRM (`mail_dialog.py`)
Herramienta de comunicación directa con clientes y administradores de flotas.
*   **Cruce Relacional por `CDB`:** Obtiene los códigos de la información seleccionada y los cruza contra los directorios disponibles para construir la lista de destinatarios.
*   **Limpieza de Destinatarios:** Elimina correos duplicados y normaliza la información antes de preparar el envío.
*   **Plantillas con Variables Dinámicas (`@FLOTA`):** El cuadro de redacción permite reemplazar variables de plantilla por información de la flota objetivo.
*   **Integración con Outlook:** Utiliza la automatización de Outlook mediante `win32com.client` para preparar y enviar los correos desde el entorno Windows.

### 6.12. Módulo de Operaciones (`operaciones.py`)
Centro de control enfocado en el seguimiento logístico y conectividad.
*   **Presentación Tabular:** Muestra los principales identificadores y estados operacionales de cada vehículo.
*   **Validación Estricta de Fechas de Baja:** Implementa validación durante la edición para mantener el estándar `DD-MM-YYYY`.
*   **Transacciones en Segundo Plano:** Delega las eliminaciones y modificaciones a `DeleteRowThread` y `SaveExcelThread`, manteniendo activa la interfaz durante las operaciones de escritura.

### 6.13. Módulo de Provisiones y Gestión Financiera (`provisiones.py`)
Cerebro de control para cobros, variaciones de planes y costos de conectividad.
*   **Cruce Automático Comercial-Finanzas (`SaveProvisionesThread`):** Al modificar parámetros como `Cantidad de Meses`, guarda la provisión y actualiza la información relacionada en la base comercial cuando corresponde.
*   **Rescate de Huérfanos (`RescateWorker`):** Si durante un guardado detecta información de provisiones que no existe en la base comercial, utiliza un flujo de rescate para localizar e incorporar los datos faltantes.
*   **Sincronización y Costos:** `SyncTerminalDialog` y `CostosDialog` permiten gestionar la incorporación de contratos y parámetros financieros. `FetchUfWorker` obtiene el valor de UF mediante una API web cuando se requiere actualizarlo.

### 6.14. Ventana Principal y Enrutador (`main_window.py`)
Contenedor raíz (`QMainWindow`) que orquesta la navegación, atajos y el estado global.
*   **Sistema de Notificaciones Dinámicas (`CompareSnapshotThread`):** Ejecuta comparaciones contra el snapshot comercial para detectar altas, bajas y modificaciones y presentar notificaciones al usuario cuando existen cambios externos.
*   **Navegación y Búsqueda Global:** Gestiona la barra lateral, la navegación entre módulos y la barra de búsqueda superior que delega el filtrado al módulo activo.
*   **Atajos de Teclado y Control de Pérdida de Datos:** Integra atajos como `Ctrl+S` y `Ctrl+F` para guardar y buscar. También coordina las señales del Watchdog y los estados de guardado de la aplicación.
*   **Módulos Registrados:** La ventana principal integra actualmente `GeneralModule`, `DashboardModule`, `ComercialModule`, `OperacionesModule`, `ProvisionesModule`, `ContratosModule`, `InstalacionesModule`, `HistorialModule`, `ContactosModule`, `ConfiguracionModule` y el diálogo de correo `MailDialog`.

### 6.15. Diálogo de Alta de Contactos (`contactos_agregar.py`)
Componente modal específico para crear nuevos contactos desde el módulo de Contactos.
*   **Formulario de Alta:** Recopila los campos necesarios para registrar un nuevo contacto.
*   **Integración con Configuración:** Utiliza las rutas configuradas para interactuar con el repositorio de contactos.
*   **Identidad Física:** El nuevo registro recibe un `ID` permanente asignado por el módulo de Contactos antes de ser guardado.

---

## 7. Repositorios de Datos Maestros

Dado que las políticas de infraestructura restringen el uso de servidores SQL, el ecosistema se sustenta sobre archivos Excel y otros archivos de configuración locales, algunos de ellos alimentados o sincronizados desde repositorios externos.

### 7.1. Archivos principales utilizados

*   `PruebasFM.xlsx` — Base comercial principal.
*   `provisionFelipe.xlsx` — Información y cálculos de provisiones.
*   `Instalaciones.xlsx` — Reportes consolidados de instalaciones.
*   `contactos.xlsx` — Directorio de contactos.
*   `BBDD CLIENTES CM.xlsx` — Fuente externa (Power BI) leída en vivo para el directorio de empresas y direcciones. (`direcciones.xlsx` fue eliminado el 02-09-2026 por ser un archivo local legado y redundante frente a esta fuente.)
*   `RM_JAVI_VOLVO CONNECT.xlsx` — Archivo maestro utilizado por la sincronización comercial.
*   `Correos.xlsx` — Repositorio utilizado por las funciones de correo.
*   `LogApp.xlsx` — Libro de auditoría de modificaciones.
*   `RegistroEliminado.xlsx` — Libro de registros eliminados.
*   `PruebasFM_BACKUP_SYNC.xlsx` — Respaldo preventivo de la base comercial cuando corresponde.
*   `.snapshot_comercial.pkl` — Snapshot binario utilizado para comparar el estado anterior y actual de la base comercial.

### 7.2. Archivos temporales y de configuración

*   `app_config.json` — Configuración de rutas y enlaces externos.
*   `config/pinned_contacts.json` — Persistencia de contactos favoritos.
*   `data/temp/` — Espacio de trabajo para copias y archivos temporales.
*   `data/backups/` — Almacenamiento de backups automáticos.
*   `logs/sistema.log` — Registro técnico de ejecución y errores.
