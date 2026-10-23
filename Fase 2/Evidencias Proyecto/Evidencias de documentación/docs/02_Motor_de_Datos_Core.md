## 1. Visión general del Core

El módulo `src/core/` es el corazón transaccional y de almacenamiento en memoria de la aplicación. Su función general es extraer datos de archivos Excel físicos, validarlos, limpiarlos, mantenerlos en memoria (RAM) usando la librería Pandas y gestionar las escrituras seguras en disco. Pandas y sus DataFrames funcionan efectivamente como el **estado central y fuente de verdad en memoria** de toda la aplicación una vez que se completa el arranque. Todas las vistas consumen copias de estos DataFrames y los modifican directa o indirectamente.

## 2. DataManager

- **Responsabilidad:** Administrar la memoria central, orquestar la carga asíncrona de los Excel y exponer los datos a la interfaz.
    
- **Patrón utilizado:** Implementa un patrón **Singleton** clásico (`__new__` verifica `_instance`), garantizando que todas las pantallas compartan la misma información.
    
- **DataFrames administrados:** Mantiene `df_master` (Comercial/General/Operaciones), `df_prov` (Provisiones), `df_contactos` (Contactos), `df_logs` y `df_deleted` (Auditoría). `df_deleted` solo contiene la **primera hoja** de `RegistroEliminado.xlsx` (se mantiene por compatibilidad, sin consumidores en la UI actual); `deleted_sheets` (expuesto vía `get_deleted_logs_sheets()`) es el dict `{módulo: DataFrame}` con **todas** las hojas del archivo, y es lo que consume la pestaña Papelera de Historial. Ver [[06. Seguridad, Integridad y Resiliencia de Datos]] §8 para el porqué de esta distinción.
    
- **Variables de estado:** Gestiona variables de bloqueo (`is_loading_main`, `is_loading_prov`, `is_loading_contactos`, `is_app_saving`), marcas de tiempo (`save_timestamp`, `last_load_time`), y constantes financieras (`valor_uf`, `valor_civ`, `lista_planes`).
    
- **Señales Qt:** Emite `data_ready`, `load_error`, `provisiones_ready`, `load_provisiones_error`, `contactos_ready` y `load_contactos_error` tras finalizar las cargas en segundo plano. También expone `logs_updated`, una señal liviana emitida por `set_logs_df()` para refrescar solo el historial en RAM sin disparar una recarga completa.
    
- **Carga de datos:** Instancia objetos `QThread` específicos (`MainDataLoaderThread`, `ProvisionesLoaderThread`, `ContactosLoaderThread`) que leen los archivos maestros evitando colapsar la GUI. **Actualizado (23-09-2026, RG-41 — ver [[13. Matriz de Requerimientos y Trazabilidad]]):** `MainDataLoaderThread` bifurca por la extensión real de `self.filepath` — `pd.read_csv(dtype=str, keep_default_na=False)` si es `.csv`, `pd.read_excel(sheet_name='BBDD (2)')` si es `.xlsx` (con el mismo fallback histórico sin `sheet_name` si esa hoja no existe); el resto del pipeline (`DataFrameFormatter.clean()`, columnas de fecha "legado") es idéntico para ambos formatos. `EXCEL_PATH` en producción apunta hoy a `PruebasFM.csv` (cutover ejecutado el 23-09-2026); `PruebasFM.xlsx` se conserva intacto sin usarse. `MainDataLoaderThread` y `ContactosLoaderThread` reintentan (hasta 5 veces) copiando el archivo bloqueado a un archivo "ghost" temporal (`ghost_main.csv`/`ghost_main.xlsx` según corresponda, `ghost_contactos.xlsx`) cuando la lectura falla por `PermissionError` (típico de un archivo abierto por el usuario o bloqueado por SharePoint). `ContactosLoaderThread` además valida estrictamente la columna `ID`: exige que exista y rechaza con error fatal cualquier valor vacío, duplicado o no numérico. **Actualizado (28-09-2026, rendimiento):** `ProvisionesLoaderThread` abre `provisionFelipe.xlsx` una sola vez (`pd.ExcelFile`) para las hojas `Variables`, `Planes` y `Prov` (antes, 3 lecturas completas), y `MainDataLoaderThread` lee `RegistroEliminado.xlsx` una sola vez (`sheet_name=None`) y toma la primera hoja como `df_deleted` (antes, 2 lecturas). El resultado no cambia.

- **Lectura principal reutilizable y precarga (28-09-2026, Fase 2 de rendimiento):**
    - El cuerpo de `MainDataLoaderThread.run()` vive ahora en la función de módulo `leer_datos_principales(filepath)`, que devuelve la tupla `(df, df_logs, df_deleted, load_time, deleted_sheets)`. El hilo solo la invoca y emite el resultado.
    - El archivo "ghost" usa un nombre único (`ghost_main_<uuid>.<ext>`) y se borra al terminar, porque ahora dos hilos pueden leer a la vez (carga normal y `CompareSnapshotThread`).
    - `guardar_precarga_principal(payload, ruta, mtime)` guarda una lectura ya hecha. El siguiente `load_data_async()` la consume una sola vez, sin lanzar hilo, si la ruta coincide, tiene como máximo `VIGENCIA_PRECARGA_SEGUNDOS` (300 s) y el `mtime` del archivo no cambió. Si no, la descarta y lee normalmente. La producen `CompareSnapshotThread` (§8) y, desde el 01-10-2026, el arranque (`PrecargaDatosThread` de `main.py`, que lee mientras corre la animación del splash; ver [[01_Arranque_y_Configuracion]] §3.7).
    - **Fechas legado por tramos (01-10-2026):** `formatear_columna_fecha_legado` convierte las fechas a texto con `_strftime_por_tramos` (tramos de `FILAS_POR_TRAMO_STRFTIME` = 2.000 filas). El resultado es idéntico a un `strftime` de una vez. El motivo: un solo `strftime` sobre 12.000 filas retiene el GIL ~80 ms y congela la interfaz aunque la lectura corra en otro hilo (ver [[12. Rendimiento y Optimizaciones de Interfaz]] §12).

- **Guard de reentrancia (28-09-2026):** si `load_data_async()` o `load_provisiones_async()` se llaman con una carga en curso, marcan `_main_reload_pending`/`_prov_reload_pending` y retornan sin emitir. Al terminar la carga actual se relanza una sola vez y solo esa emite `data_ready`/`provisiones_ready`. Antes se emitía la señal de inmediato con los datos viejos. Los módulos de UI ya no fuerzan `is_loading_main`/`is_loading_prov = False` para saltarse la guarda.
    
- **Diagnóstico:** `get_system_health()` expone el estado de memoria RAM, filas cargadas por DataFrame, conteo de backups existentes (**actualizado 23-09-2026:** cuenta por la extensión real de `EXCEL_PATH`, no hardcodeada a `.xlsx`) y estado de `logs/sistema.log` (**28-09-2026:** lee solo los últimos 64 KB del archivo, de donde salen las 50 líneas que analiza, en vez de cargarlo completo en cada `data_ready`), consumido por `ConfiguracionModule` para el panel de diagnóstico.
    
- **Relación con otros:** Las interfaces de usuario consumen sus _getters_ (ej. `get_comercial_df()`) que devuelven `.copy()` para aislar la vista de la base. Sin embargo, los módulos de UI inyectan datos directamente en sus variables internas (ej. `dm.df_master = df_m_copy`) tras guardados exitosos.
    

## 3. DataFrameFormatter

- **Propósito:** Preprocesamiento y normalización estricta de DataFrames.
    
- **Validaciones:** `_validate_columns` exige las columnas `VIN` y `CHASIS`. Levanta un `ValueError` si faltan, abortando la carga principal.
    
- **Limpieza y conversiones:** Borra sufijos nulos (`.0`), fuerza enteros donde corresponde y unifica representaciones vacías (`nan`, `NaT`) a cadenas vacías.
    
- **Reglas de negocio (Cálculos):** Recalcula matemáticamente la columna `TÉRMINO CONTRATO` sumando `DURACIÓN (MESES)` a `INICIO CONTRATO` y estandariza todas las fechas a `DD-MM-YYYY` mediante la función `format_date_fast`. También normaliza las columnas `TIPO DE SERVICIO`, `FORMA DE CONTRATO`, `ESTADO COMERCIAL` y `ESTADO DEL CM` (nuevo 11-09-2026, Title Case fijo: `Running`/`Expired`/`Terminated`) contra catálogos fijos (`TIPO_SERVICIO_MAP`, `FORMA_CONTRATO_MAP`, `ESTADO_COMERCIAL_MAP`, `ESTADO_DEL_CM_MAP` en `src/core/constants.py`), dejando intacto cualquier valor no mapeado. Detalle de negocio de `ESTADO DEL CM` en [[07. Procesos y Reglas de Negocio]] §1 y §4. Además calcula la columna `ETAPA GESTIÓN` (`calcular_etapa_gestion_esperada`) combinando `TIPO DE FACTURACION` (prioridad 1) y `ESTADO_COMERCIAL_ETAPA_MAP` (prioridad 2), como única fuente de verdad de esa columna.
    
- **Quién lo utiliza:** Es invocado por `MainDataLoaderThread` (dentro de DataManager) y `ExcelReader` (para snapshots). También es utilizado por `RMJaviSyncWorker` para limpiar la base tras la sincronización.

- **Rendimiento (28-09-2026):** los cálculos por fila (`calcular_termino`, ETAPA GESTIÓN) y el formateo de fechas se evalúan una vez por combinación o valor distinto. Para eso se usan `aplicar_por_fila_memoizado(df, func, columnas)`, que equivale a `df.apply(func, axis=1)` cuando `func` solo lee esas columnas, y `_memoizar_por_valor`. `DataFrameFormatter.calcular_etapa_gestion_df(df)` expone la regla de ETAPA GESTIÓN para todo el DataFrame y la reutiliza `RMJaviSyncWorker`; `ProvisionesLoaderThread` usa el mismo helper. Las reglas no cambiaron. Mediciones en [[12. Rendimiento y Optimizaciones de Interfaz]] §7.4.
- **Copia de provisiones (20-10-2026):** `ProvisionesLoaderThread` guarda el resultado de leer `provisionFelipe.xlsx` (registros, planes, UF y CIV) en `data/cache/provisiones_<hash de ruta>.pkl`. En la lectura siguiente lo usa solo si el Excel conserva la fecha de modificación (en ns) y el tamaño que tenía al empezar la lectura anterior; cualquier escritura, propia o externa, obliga a releer el Excel. Escritura atómica; se borran las copias de otras rutas (por ejemplo las de los tests). Detalle en [[12. Rendimiento y Optimizaciones de Interfaz]] §14.
    

## 4. ExcelReader

- **Archivos que lee:** Principalmente `EXCEL_PATH`, `LOG_CSV_PATH` (el historial oficial `LogApp.csv`, leído vía `pd.read_csv`; ya no `LOG_EXCEL_PATH`) y `DELETED_LOG_EXCEL_PATH`.
    
- **Actualizado (23-09-2026, RG-41):** `get_commercial_data()`, `get_general_data()` y `get_operaciones_data()` ya no llaman `pd.read_excel()` de forma incondicional — pasan por `_leer_dataframe()`, que bifurca por extensión igual que `MainDataLoaderThread` (`pd.read_csv(dtype=str, keep_default_na=False)` si `self.filepath` termina en `.csv`, `pd.read_excel()` si no). Este era el hallazgo bloqueante de la fase de ensayo previa al cutover de `PruebasFM.csv`: sin esta bifurcación, `compare_snapshot()` (punto siguiente) quedaba silenciosamente roto contra un `EXCEL_PATH` en `.csv` — nunca crasheaba (el error quedaba atrapado más arriba en la cadena de llamadas), pero jamás detectaba cambios externos reales.
    
- **Snapshot y compare_snapshot:** Crea una copia binaria rápida de la base comercial usando la librería `pickle`. Su método `compare_snapshot` extrae el archivo nuevamente y cruza ambos DataFrames usando la columna `VIN` como identificador único para detectar Altas, Bajas y Modificaciones externas. Posee un mecanismo de "Auto-Heal" que ignora los cambios si superan los 200 registros.
    - **Actualizado 28-09-2026:** el snapshot ya no vive junto a `EXCEL_PATH` (carpeta sincronizada con OneDrive/SharePoint). Ahora se guarda en `data/cache/snapshot_comercial_<hash>.pkl`, donde el hash son 12 caracteres del MD5 de la ruta absoluta de `EXCEL_PATH`. El antiguo `.snapshot_comercial.pkl` no se borra ni se lee.
    - `compare_snapshot_desde_df(df_limpio)` hace la misma comparación sobre un DataFrame ya leído y limpio, tomando las columnas de `COLUMNAS_SNAPSHOT_COMERCIAL`. Es la que usa `CompareSnapshotThread`.
    - **Actualizado 07-10-2026:** `COLUMNAS_SNAPSHOT_COMERCIAL` tiene ahora 30 columnas (se agregaron RAZÓN SOCIAL, FECHA DE BAJA, ESTADO DE ENTREGA, PERIODO INTERNO, OBSERVACIONES, TIPO DE CM, FECHA INICIO CM y FECHA TERMINO CM, y se corrigió `TIPO DE FACTURACION`, que se buscaba con tilde y nunca se comparaba). Detalle en [[05. Flujos de Datos y Sincronización]] §5.
    - Tras comparar, el snapshot nuevo se guarda desde esos mismos datos. Antes se llamaba a `create_snapshot()`, que volvía a leer y limpiar el archivo.
    - `create_snapshot()` no se invoca desde el código de la app, solo desde tests. Por eso un guardado propio no actualiza el snapshot.
    
- **Duplicación confirmada:** NO es utilizado por `DataManager` para cargar la RAM. Duplica la lógica de lectura ejecutando su propia lectura (`_leer_dataframe()`) de forma separada — el problema de duplicación en sí no se corrigió (no era el alcance del cutover a CSV), solo se le agregó soporte para ambos formatos.
    

## 5. ExcelWriter

- **Métodos y archivos:** Expone `overwrite_dataframe`, `update_cells`, `delete_row`, `add_new_row` y `add_new_rows_batch` (esta última para inserciones en lote con un solo backup/log — usada por la importación de Power BI, ver [[03_Vistas_y_Navegacion_UI]]). Modifica dinámicamente cualquier ruta que se le inyecte por el parámetro `custom_filepath`.
    
- **Actualizado (23-09-2026, RG-41):** los cuatro métodos anteriores bifurcan al inicio por la extensión de `target_file`. Contra un `.csv`, delegan en `src/core/excel_writer_csv_backend.py` (`update_cells_csv`, `add_new_row_csv`, `delete_row_csv`, `add_new_rows_batch_csv`), que reimplementa el mismo contrato/comportamiento operando sobre un `DataFrame` (`pd.read_csv`/`to_csv`) en vez de un `Workbook` de `openpyxl` — mismo criterio de backup previo, log de auditoría, `is_app_saving`/`save_timestamp` y escritura atómica (temporal + `fsync` + `shutil.copy2`), pero sin usar `WorkbookCache` (es específico de `openpyxl.Workbook`, no aplica a CSV): usa en su lugar un lock por ruta propio y más liviano (`_lock_para`). La rama `.xlsx` original (descrita en el ciclo de vida de abajo) quedó sin cambios.
    
- **Escritura por ID de contrato (09-10-2026, solo rama `.csv`):** si el archivo tiene las columnas `ID` y `VIN` (`PruebasFM`; `contactos` tiene `ID` pero no `VIN`, por eso no se le aplica):
    - `update_cells_csv`: un cambio que traiga `ID` ubica la fila por ID (texto entero, tolera ".0"), así un VIN con dos contratos edita el contrato correcto. Un ID que no existe cancela todo el lote, como ya pasaba con el VIN. Sin `ID` (o con `keys`) conserva el comportamiento anterior por VIN.
    - `add_new_row_csv` y `add_new_rows_batch_csv`: si la fila no trae ID, se le asigna el máximo ID del archivo más 1 (en lote, correlativos), dentro del mismo bloqueo de escritura. Un ID que ya viene en la fila se respeta. El identificador del registro en el log sigue siendo el VIN.
    - `delete_row_csv`: se elimina por ID con `keys_dict={'ID': ...}` (el mecanismo `keys_dict` ya existía).
    - Un archivo sin columna `ID` se comporta como antes. La rama `.xlsx` no cambió. Hasta que las pantallas envíen el ID en sus cambios, siguen ubicando por VIN. Reglas en [[07. Procesos y Reglas de Negocio]] §1.aa.
    
- **Ciclo de vida — rama `.xlsx` (Backups y Temporales):**
    
    1. Activa `dm.is_app_saving = True` y `save_timestamp`.
        
    2. Ejecuta `_crear_backup`, clonando el archivo original en `/data/backups/` con fecha y hora. **Confirmado:** `update_cells`, `add_new_row`, `delete_row` y `overwrite_dataframe` verifican `self.last_backup_ok` justo después y abortan la escritura (sin tocar el archivo real) si el backup falló.
        
    3. Crea un archivo temporal UUID en `/data/temp/` y clona el original allí.
        
    4. Modifica el temporal usando `openpyxl` (o `pandas` para overwrite).
        
    5. Ejecuta `os.fsync` para asegurar escritura en disco físico.
        
    6. Copia el temporal sobre el archivo original con `shutil.copy2` (no es un `os.replace`/rename atómico de sistema operativo, a diferencia de la migración de historiales legacy — ver 5.1 — que sí usa `os.replace`) y registra la acción en `LogApp.csv` (historial oficial de modificaciones) o `RegistroEliminado.xlsx` (papelera de eliminados).
        
- **Concurrencia:** Los métodos de `ExcelWriter` son **100% sincrónicos y bloqueantes** internamente.
    
- **Confirmado — `_log_deleted` protegido:** El registro de eliminaciones (`RegistroEliminado.xlsx`) también sigue el Punto C: crea backup antes de guardar y, si no puede leer el archivo existente, aborta el registro sin modificarlo en vez de recrearlo desde cero. Además, si el esquema de columnas del módulo de origen cambia respecto a la hoja ya existente, `_log_deleted` no la sobrescribe: crea una hoja nueva versionada (ej. `"Base (2)"`, vía `_siguiente_nombre_hoja_version`) para no mezclar ni corromper el histórico con columnas incompatibles. Detalle e historial del hallazgo en [[06. Seguridad, Integridad y Resiliencia de Datos]]. **Nuevo (07-10-2026):** `_log_deleted` delega ahora en `_log_deleted_lote`, que registra varias filas eliminadas con una sola apertura, backup y guardado del archivo; `ComercialModule` lo usa en su paso de auditoría al eliminar varias unidades.
    

## 5.1 mail_registro.py (`src/services/`)

> Nota: este módulo vive en `src/services/`, no en `src/core/`. Se documenta aquí, junto a `ExcelWriter`, por compartir el mismo tipo de responsabilidad (persistencia de un historial transaccional) y patrones (migración atómica no destructiva, escritura tolerante a fallos).

- **Responsabilidad:** Persistir el historial de correos enviados (`Historial_Envios_VC.csv`) de forma independiente de la UI. Antes, `mail_dialog.py` leía y reescribía `Historial_Envios_VC.xlsx` completo directamente dentro de `OutlookSenderThread`.
    
- **Por qué se separó de la UI:** Mantener la lógica de registro fuera de `mail_dialog.py` permite (a) probarla con pruebas unitarias puras sin levantar PyQt6 ni mockear Outlook/COM, y (b) aplicarle el mismo patrón append-only ya validado en `LogApp.csv` sin mezclarlo con la lógica de envío de correos.
    
- **Funciones expuestas:**
    - `construir_registro(id_envio, fecha_hora, tipo_correo, razon_social, chasis, destinatario, estado, asunto)`: arma un registro de historial con las claves de `_COLUMNAS`. **Nuevo (03-09-2026):** única fuente de verdad del esquema del historial — antes `OutlookSenderThread.run()` armaba el diccionario a mano, duplicando los nombres de columna ya definidos en `_COLUMNAS`.
    - `registrar_envios(historial_records)`: agrega filas nuevas al CSV oficial sin releer el historial completo (append-only). Nunca lanza excepción; devuelve `True`/`False`.
    - `leer_historial()`: devuelve el historial completo como DataFrame (usado por `RegistroEnviosDialog` en `mail_dialog.py` para mostrarlo en pantalla).
    - `migrar_historial_legacy()`: migración única e idempotente desde el `.xlsx` legado hacia el CSV oficial, con verificación de conteo de filas antes de reemplazar (`os.replace` atómico). El `.xlsx` original nunca se modifica ni se borra. Se invoca automáticamente al inicio de `registrar_envios` y `leer_historial`.
    
- **Quién lo usa:** `OutlookSenderThread.run()` (en `mail_dialog.py`) llama a `construir_registro` para armar cada fila y luego a `registrar_envios` tras el envío, propagando el resultado (`registro_ok`) en `finished_signal` para que la UI pueda avisar si el registro falló aunque el correo se haya enviado. `RegistroEnviosDialog` (diálogo en `mail_dialog.py`, reutiliza `VolvoTableWidget`/`PandasTableModel`) llama a `leer_historial` para mostrar el historial completo.
    
- **Relación con los demás servicios de Correos (03-09-2026):** `mail_registro.py` sigue siendo exclusivamente el historial. La preparación de destinatarios/plantillas (`src/services/mail_service.py`), el cruce/persistencia de `Correos.xlsx` (`src/services/mail_sync_service.py`) y el puente Contactos→Correos.xlsx para altas puntuales de contacto (`src/services/contacto_correo_service.py`, nuevo 03-09-2026) son servicios hermanos, no documentados en esta sección por no compartir su responsabilidad de persistencia de historial — ver [[03_Vistas_y_Navegacion_UI]] §8 y [[08. Arquitectura Visual y Diagramas]] §7.1 para su rol dentro del flujo de Correos.

## 6. FileWatcher

- **Funcionamiento:** Monitoriza la carpeta `WATCH_DIR` usando la librería `watchdog` dentro del hilo `WatchdogThread`.
    
- **Relación con DataManager (Debouncer/Silenciador):** Posee un freno de 5 segundos para eventos en ráfaga. Su función vital es el silenciador (**actualizado 28-09-2026**): descarta el evento si el último guardado propio (`dm.save_timestamp`) fue hace menos de 30 s, o si hay un guardado en curso (`dm.is_app_saving`) iniciado hace menos de 300 s. De lo contrario, emite `file_changed_signal`. Ya no exige que `is_app_saving` siga activa ni la modifica. Detalle y motivo en [[06. Seguridad, Integridad y Resiliencia de Datos]] §5.
    

## 7. SharePointSync

- **Funcionamiento REAL:** No utiliza API. Simula una descarga humana abriendo el enlace de SharePoint en el navegador por defecto del sistema (`webbrowser.open`).
    
- **Detección:** Escanea (sin recursividad, solo el nivel superior vía `glob.glob`) el directorio de "Descargas" del SO (`QStandardPaths.DownloadLocation`) hasta por 60 segundos buscando un archivo que coincida con `Provision Contratos-RpySS*.xlsx`.
    
- **Procesamiento y Deduplicación:** Mueve el archivo a `/data/temp/`, lee la hoja del año en curso (o la de año más reciente si aún no existe; antes era fija "2026"), formatea las fechas e identifica nuevos registros filtrando aquellos cuya combinación `AÑO - MES_VIN` ya exista en el Excel local `provisionFelipe.xlsx`.
    
- **Inyección (Copiar Fórmulas):** Abre el Excel local con `openpyxl`, añade las filas nuevas al final de la tabla e inyecta dinámicamente las fórmulas matemáticas (usando `Translator` de `openpyxl.formula.translate`) arrastrándolas desde la fila superior.
    
- **Excepción al ciclo de vida seguro de la sección 5:** la fase de inyección solo usa `ExcelWriter()._crear_backup()` para el respaldo previo; el guardado real es `wb.save(PROVISION_EXCEL_PATH)` directo, sin archivo temporal en `/data/temp/` ni `os.fsync` de resguardo — a diferencia del resto de escrituras de la aplicación. `SharePointSyncWorker` es además una única instancia de `QThread` reutilizada en dos fases (detección e inyección) mediante el flag `self.is_injecting`, no dos hilos separados.
    

## 8. Integración de la Interfaz con el Core (Auditoría de UI)

> Ver el lado UI de esta integración en [[03_Vistas_y_Navegacion_UI]].

- **Quién instancia:**
    
    - `DataManager`: Es instanciado múltiples veces (al ser Singleton retorna la misma memoria) en `MainWindow`, `ComercialModule`, `ProvisionesModule` y `ContactosModule`.
        
    - `ExcelReader`: Solo es instanciado por `MainWindow` para utilizar su método de comparación.
        
    - `ExcelWriter`: Instanciado por `ComercialModule`, `ProvisionesModule`, `ContactosModule` y `RescateWorker`. **Actualizado (03-09-2026):** también instanciado directamente por `MailDialog` (`_abrir_agregar_correo`, para `add_new_row` en `contactos.xlsx`) y por `contacto_correo_service.py` (para `update_cells` en `Correos.xlsx`) — ver [[03_Vistas_y_Navegacion_UI]] §8.
        
- **Quién inicia las cargas:**
    
    - `load_data_async()`: Lanzado por `MainWindow` en el arranque y en los botones "Recargar" o funciones de auto-heal de Provisiones y Comercial.
        
    - `load_provisiones_async()`: Lanzado internamente en cadena por `_ejecutar_cargas()` de `ProvisionesModule`.
        
    - `load_contactos_async()`: Lanzado directamente por `ContactosModule` al cargarse. **Actualizado (03-09-2026):** también lanzado por `MailDialog` tras agregar un contacto desde "Agregar correo relacionado a esta empresa", para mantener el caché global (`df_contactos`) sincronizado igual que hace `ContactosModule` tras su propia alta.
        
    - **Actualizado (02-09-2026):** `ContactosModule` ya no depende de `direcciones.xlsx` (archivo local legado, eliminado de `app_config.json` y de todo el código). En su lugar, lanza en paralelo un segundo worker (`PowerBiSyncWorker`) que lee `POWERBI_EXCEL_PATH` (`BBDD CLIENTES CM.xlsx`) de forma asíncrona para obtener las direcciones/empresas. La pantalla de Contactos muestra un loading screen (spinner, igual al de Provisiones) hasta que ambas cargas (`contactos.xlsx` vía `load_contactos_async` y `BBDD CLIENTES CM.xlsx` vía `PowerBiSyncWorker`) terminan.
        
- **Quien escucha señales:**
    
    - `data_ready`: Escuchada por `MainWindow` (para desbloquear el menú e iniciar Watchdog) y `ComercialModule` (para repoblar la tabla).
        
    - `provisiones_ready` y `contactos_ready`: Escuchadas por sus respectivos módulos para inicializar las tablas.
        
- **Hilos de Escritura (Crucial para Concurrencia):**
    
    Como `ExcelWriter` es bloqueante, la UI ha implementado wrappers de `QThread` para cada operación de escritura. En lugar de llamar al `writer` directamente, los módulos instancian hilos paralelos:
    
    - Comercial: `SaveExcelThread`, `AddRowThread` (`DeleteRowThread` se retiró el 09-10-2026 junto con "Eliminar fila").
        
    - Provisiones: `SaveProvisionesThread`.
        
    - Contactos: `SaveContactosThread`, `AddContactoThread`, `DeleteContactoThread`.

    - **Excepción detectada (NUEVO — 03-09-2026):** `MailDialog._abrir_agregar_correo()` llama a `ExcelWriter().add_new_row(...)` y a `contacto_correo_service.actualizar_correo_por_cdb()` (que a su vez llama a `ExcelWriter().update_cells(...)`) **directamente en el hilo principal, sin wrapper `QThread`**, rompiendo el patrón de esta sección. Se preservó así porque es el comportamiento que ya tenía el flujo de sincronización de Correos (`SyncCorreosDialog.save_data()` también llama a `mail_sync_service.guardar_correos_excel()` de forma síncrona) y no se pidió cambiarlo; puede congelar brevemente la UI mientras escribe ambos Excel. Riesgo menor, no corregido — ver [[03_Vistas_y_Navegacion_UI]] §10 para el resto de bloqueos síncronos conocidos del módulo de Correos.
        
    - **Excepción preexistente confirmada (auditoría 03-09-2026):** `CostosDialog.save_and_close()` (en `provisiones.py`) también escribe `provisionFelipe.xlsx` **directamente en el hilo principal** (`openpyxl.load_workbook`/`wb.save`, con `ExcelWriter._crear_backup()` previo pero sin wrapper `QThread`), el mismo patrón de excepción que `MailDialog._abrir_agregar_correo()`. No es una regresión de esta fecha ni se corrigió: no se pidió, y el backup previo sigue siendo obligatorio y bloqueante ante fallo — solo un riesgo de UI congelada brevemente al guardar Ajustes de Costos.
        
- **Actualización del Estado en RAM (Inyección Post-Guardado):** Para evitar leer el archivo completo desde el disco tras cada guardado, los módulos incluyen código que inyecta los datos directamente al Singleton. Por ejemplo, `ComercialModule` en su función `_on_save_finished` realiza un volcado: `df_m_copy.loc[mask, col] = val` y luego `dm.df_master = df_m_copy`.
    
- **Cruce de Módulos (Provisiones a Comercial):** Cuando se guarda una provisión, el hilo `SaveProvisionesThread` verifica si hay datos comerciales afectados (`cross_updates`). De ser así, ejecuta un segundo guardado mediante `ExcelWriter.update_cells` dirigido al archivo comercial (`EXCEL_PATH`, hoy `PruebasFM.csv`) y posteriormente actualiza ambos DataFrames (`dm.df_master` y `dm.df_prov`) en memoria. **Actualizado (03-09-2026):** la normalización de `provisiones_changes` (payload para `update_cells` sobre Provisiones) y el cálculo de `PERIODO INTERNO` se extrajeron a `provisiones_services.construir_cambios_provisiones()`/`convertir_periodo_interno()`, funciones puras testeadas sin PyQt6. El resto del bloque (`cross_updates`, lectura de `INICIO CONTRATO` en `df_master` y proyección de `TÉRMINO CONTRATO` vía `relativedelta`) permanece sin cambios dentro del thread — deliberadamente no extraído por duplicar `DataFrameFormatter.calcular_termino()`.
    
- **Reacción a FileWatcher (Cambio Externo):** El `Watchdog` emite una señal que atrapa `MainWindow`. Este ejecuta `CompareSnapshotThread` (usando `ExcelReader`). Al finalizar, notifica al usuario; si el usuario acepta, `MainWindow` fuerza un `data_manager.load_data_async()` para actualizar la aplicación completa con la base externa.
    - **Actualizado 28-09-2026:** `CompareSnapshotThread` lee con `leer_datos_principales()`, compara con `compare_snapshot_desde_df()` y guarda la lectura como precarga (§2). La recarga posterior la reutiliza, así que el archivo se lee y se limpia una sola vez por cambio externo, en vez de hasta tres.
    

## 9. Concurrencia y rendimiento

- **Asincronía real (QThread):** Todas las cargas pesadas de archivos (`pd.read_excel`), todas las modificaciones CRUD sobre Excel (`ExcelWriter`), el monitoreo del disco (`Watchdog`) y las sincronizaciones de SharePoint se ejecutan estrictamente en hilos separados (Background Threads).
    
- **Protección del Hilo Principal:** Gracias a los Wrappers creados en la UI (ej. `SaveExcelThread`), la interfaz gráfica **no sufre congelamientos confirmados** durante lectura o escritura.
    
- **Cuellos de Botella Confirmados:** El formateo de fechas (`DataFrameFormatter`) itera masivamente strings y el `compare_snapshot` procesa el Excel entero cruzándolo con la RAM. Aunque están aislados en hilos y no congelan la interfaz, impactan fuertemente en el tiempo de procesamiento (Load Time).
    - **Matiz (auditoría 28-09-2026):** la afirmación "no congelan la interfaz" es parcial. El trabajo Python puro en un `QThread` compite por el GIL con el hilo de UI y la traba igual. Diagnóstico y medidas en [[12. Rendimiento y Optimizaciones de Interfaz]] §7.
    

## 10. Persistencia

- **Fuente Persistente (Maestros):** Los archivos físicos locales (ej. `PruebasFM.csv` — cutover ejecutado 23-09-2026, antes `PruebasFM.xlsx`, ver RG-41 en [[13. Matriz de Requerimientos y Trazabilidad]] —, `provisionFelipe.xlsx`). El formato del archivo maestro principal (`EXCEL_PATH`) puede ser `.xlsx` o `.csv` indistintamente: todo el pipeline de lectura/escritura (`MainDataLoaderThread`, `ExcelWriter`, `ExcelReader`) bifurca por extensión.
    
- **Estado en Memoria:** DataFrames dentro del Singleton `DataManager`.
    
- **Archivos Temporales:** `/data/temp/` almacena clones de Excel durante escrituras y cruces asíncronos para proteger el original si falla el proceso.
    
- **Backups:** tres mecanismos independientes y complementarios (detalle en [[06. Seguridad, Integridad y Resiliencia de Datos]]):
    - `/data/backups/` — copia previa de UN archivo justo antes de modificarlo (`ExcelWriter._crear_backup`), últimas 10 instantáneas por archivo.
    - `/data/backup_auto/` — snapshot completo automático de todos los archivos maestros, disparado al iniciar la app los viernes (máximo uno por semana ISO), retiene los últimos 5. Implementado por `BackupManager` (`src/core/backup_manager.py`), ejecutado fuera del hilo principal por `BackupWorker` (`QThread`).
    - `/data/backupManual/` — snapshot completo bajo demanda desde Configuración ("Realizar backup completo"), sin retención automática. También implementado por `BackupManager`/`BackupWorker`.
    
- **Logs de Auditoría:** `LogApp.csv` (historial oficial de modificaciones, migrado una única vez desde el antiguo `LogApp.xlsx` + `LogApp_incremental.csv`) y `RegistroEliminado.xlsx` (papelera de eliminados) almacenan trazas de las escrituras. De forma análoga, `Historial_Envios_VC.csv` (gestionado por `mail_registro.py`, ver sección 5.1) almacena el historial de correos enviados, migrado una única vez desde el antiguo `Historial_Envios_VC.xlsx`.
    
- **Caché:** `data/cache/snapshot_comercial_<hash>.pkl` (antes `.snapshot_comercial.pkl` junto a `EXCEL_PATH`, ver §4) actúa como caché rápido del último estado conocido para detectar colisiones.
    

## 11. Comparación con ARCHITECTURE.md

- Lógica Asíncrona (Data Manager y UI Workers): **CONFIRMADO**. El código demuestra el uso exhaustivo de QThread.
    
- Base Comercial como fuente de verdad: **CONFIRMADO**. Todas las rutas apuntan a un Excel maestro.
    
- Mecanismo de Temp y Backups: **CONFIRMADO**.
    
- Watchdog y Freno de eventos: **CONFIRMADO**.
    
- Base de Datos SQL: **CONFIRMADO AUSENTE**. Todo es Pandas y Openpyxl.
    

## 12. Problemas y Riesgos Confirmados

### Problemas confirmados

- **Ruptura del Encapsulamiento del Singleton:** Los módulos de UI (Comercial, Provisiones, Contactos) modifican directamente los atributos internos del `DataManager` (ej. `dm.df_master = df_m_copy`) en lugar de utilizar métodos de actualización (`Setters`). Esto es una violación arquitectónica clara (análisis extendido en [[04. Arquitectura y Patrones del Sistema]]).
    
- **Duplicación de código de lectura:** `ExcelReader` implementa lógicas de Pandas redundantes que ya realiza `DataManager`.
    

### Riesgos potenciales

- **Sincronización Frágil:** `SharePointSyncWorker` y `RescateWorker` asumen que el navegador abrirá, el usuario está logueado, y la ruta de Descargas es `C:\Users\...`. Cualquier intervención del OS fallará el `time.sleep`.
    
- **Inconsistencia RAM vs Disco:** Al inyectar los cambios en RAM manualmente después de guardar con `ExcelWriter` (para no recargar el Excel completo), si la lógica de inyección de un módulo no es idéntica a lo que Openpyxl escribió, la interfaz mostrará algo distinto a lo que hay en el archivo hasta el próximo reinicio.
    - **Confirmado como bug real (02-09-2026):** En `ComercialModule._on_save_finished`, la inyección post-guardado reasignaba `self.df_base` desde `get_comercial_df()` sin reaplicar el mismo preprocesamiento que `load_data()` (limpieza de `CDB`/`DURACIÓN (MESES)`, ajuste de `TÉRMINO CONTRATO` y, sobre todo, el cálculo de la columna auxiliar `PAGO CM_NUM`). Como esa ruta además activa `_skip_self_triggered_reload` (evita que `_on_global_data_ready` vuelva a llamar `load_data()`), el `df_base` quedaba permanentemente incompleto tras cada guardado. El siguiente uso del buscador global (`MainWindow._on_global_search` → `filter_table()`) lanzaba `KeyError: 'PAGO CM_NUM'` y crasheaba la app. **Corregido:** se extrajo el preprocesamiento a `ComercialModule._procesar_df_base()`, usado ahora tanto por `load_data()` como por `_on_save_finished()`. Detalle de módulo en [[03_Vistas_y_Navegacion_UI]].

---

## Documentos relacionados

- [[13. Matriz de Requerimientos y Trazabilidad]] — RG-41 (migración de `PruebasFM.xlsx` a `PruebasFM.csv`, backend CSV de `ExcelWriter`, cutover)
- [[03_Vistas_y_Navegacion_UI]] — cómo la UI consume e integra estos componentes
- [[04. Arquitectura y Patrones del Sistema]] — patrones de diseño (Singleton, Store Global) aplicados a DataManager
- [[05. Flujos de Datos y Sincronización]] — flujos que orquestan ExcelReader, ExcelWriter y FileWatcher
- [[06. Seguridad, Integridad y Resiliencia de Datos]] — mecanismos de seguridad de ExcelWriter y FileWatcher en detalle
- [[07. Procesos y Reglas de Negocio]] — reglas que dependen de DataFrameFormatter y ExcelReader
- [[08. Arquitectura Visual y Diagramas]] — diagrama visual del DataManager y del flujo de guardado (§2 y §3)