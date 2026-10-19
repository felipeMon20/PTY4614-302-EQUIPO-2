### 1. Resumen del arranque actual

**Actualizado 01-10-2026:** se fija el entorno gráfico (sin el modo oscuro de Windows) y se levanta una pantalla de inicio animada que no depende del tema de la app. Mientras se anima, un hilo de fondo (`PrecargaDatosThread`) lee el archivo principal. `MainWindow` se construye recién cuando la animación terminó y los datos están leídos, y reutiliza esa lectura. Detalle completo en [[01_Arranque_y_Configuracion]] §3.6-3.8.

### 2. Análisis de main.py

Este archivo es el punto de entrada directo y realiza las siguientes acciones:

- **Desactiva el modo oscuro:** Modifica la variable de entorno `QT_QPA_PLATFORM` a `windows:darkmode=0`.
    
- **Inicializa la aplicación:** Crea el objeto principal `QApplication(sys.argv)`.
    
- **Fuerza la paleta gráfica:** Establece explícitamente el estilo "Fusion" y asigna una paleta de colores claros (blancos y grises) a los roles de la interfaz.
    
- **Carga la hoja de estilos:** Llama a `load_stylesheet`, la cual lee e inyecta el archivo local `src/assets/styles.qss`.
    
- **Genera el ícono de la app:** Utiliza `create_white_background_icon` para procesar el logo (`src/assets/splash_logo.png`), dándole fondo blanco, y lo asigna a la ventana.
    
- **Agrupa el proceso en Windows:** Utiliza `ctypes` para asignar un identificador (`gestor.sscc.gestion.1`) al proceso, lo que afecta cómo se agrupa en la barra de tareas.
    
- **Carga el Splash Screen (actualizado 01-10-2026):** Instancia `CustomSplashScreen`, que hereda la animación de `src/ui/pantalla_inicio.py` (dibujada con `QPainter`, sin hojas de estilo).
    
- **Animación y transición (actualizado 01-10-2026):** La lectura de datos corre en `PrecargaDatosThread` y la animación en el hilo de la interfaz. Al terminar ambas, construye y muestra `MainWindow` y el splash se desvanece. Detalle en [[01_Arranque_y_Configuracion]] §3.6-3.8.
    
- **Manejo de errores fatales:** Si la creación de la ventana principal falla, captura la excepción, la escribe en `logs/sistema.log` y muestra un `QMessageBox` crítico en pantalla antes de abortar el programa.
    

### 3. Análisis de settings.py

Este módulo funciona como el proveedor global de las variables de configuración.

- **Responsabilidad principal:** Determinar la ruta base de ejecución (evaluando si es un `.exe` congelado por PyInstaller o un script) y asegurar la lectura/escritura del archivo `app_config.json`.
    
- **Carga y contingencia (`load_config`):** Intenta localizar `app_config.json`. Si no existe, lo crea automáticamente volcando el diccionario `DEFAULT_CONFIG`. Si existe, lo lee y lo compara con `DEFAULT_CONFIG`, inyectando cualquier llave que esté ausente en el archivo local para evitar errores por versiones antiguas.
    
- **Resolución de variables:** Las llaves del JSON (como `EXCEL_PATH` o `POWERBI_EMBED_URL`) se extraen y se dejan expuestas como variables globales en el módulo para que otros archivos las importen directamente.
    
- **Manejo de rutas dinámicas:** Calcula dinámicamente la variable `WATCH_DIR` extrayendo el nombre del directorio donde se ubica el archivo definido en `EXCEL_PATH`.
    

### 4. Configuración y archivos JSON

- **Contenido:** `app_config.json` almacena rutas absolutas de Windows (hacia el SharePoint sincronizado localmente) y URLs externas de PowerBI y SharePoint.
    
- **Relación con el código:** `app_config.example.json` es una plantilla con valores vacíos para indicar la estructura esperada.
    
- **Discrepancia en las llaves:** El diccionario `DEFAULT_CONFIG` de `settings.py` y el `app_config.example.json` incluyen la llave `"POWERBI_URL"`. Sin embargo, el archivo real `app_config.json` utiliza `"POWERBI_EMBED_URL"`. Además, en `settings.py`, la línea que extrae la variable utiliza `_current_config.get("POWERBI_EMBED_URL", "")`.
    

### 5. Dependencias relevantes

A partir de `requirements.txt`, las dependencias estrictamente relacionadas con el arranque actual son:

- **`PyQt6==6.11.0` (y sus derivados `PyQt6-Qt6`, `PyQt6_sip`):** Obligatorias para levantar `QApplication`, el Splash Screen y la interfaz principal.
    
- **`pywin32-ctypes==0.2.3` / `pywin32==312`:** Proporcionan acceso a las librerías nativas de Windows, utilizadas en `main.py` (vía `ctypes`) para configurar el ID de la aplicación en la barra de tareas.
    

### 6. Comparación con ARCHITECTURE.md

- **Coincide con el código:** El documento menciona correctamente que `main.py` carga la hoja de estilos, crea un `QTimer` para el splash screen y construye la ventana principal en segundo plano para reducir latencia. También describe de forma correcta la función de `settings.py` resolviendo el entorno y leyendo `app_config.json`.
    
- **Parcialmente coincide:** El documento menciona que el sistema extrae `POWERBI_EMBED_URL` del archivo JSON, lo cual concuerda con lo que extrae `settings.py` y el archivo real, pero omite que el `DEFAULT_CONFIG` estructural usa otro nombre para esta llave.
    
- **Desactualizado / Incompleto:** No menciona la inyección forzada del estilo "Fusion", la desactivación explícita del modo oscuro, ni el manejo y formateo del ícono de fondo blanco en `main.py`.
    
- **No puede verificarse todavía:** Múltiples secciones sobre motores de datos asíncronos y flujos de UI que no están en los archivos actuales de la auditoría.
    

### 7. Flujo de arranque

1. `main.py` → Desactiva modo oscuro en OS.
    
2. `main.py` → Inicializa `QApplication` y fuerza estilos/paleta.
    
3. `main.py` → Llama a `load_stylesheet` (lee y aplica `.qss`).
    
4. `main.py` → Configura el ícono de Windows (`ctypes`).
    
5. `main.py` → Instancia y muestra `CustomSplashScreen`.
    
6. `CustomSplashScreen.start_animation()` → Lanza `PrecargaDatosThread` (importa pandas y lee el archivo principal); la animación arranca cuando el hilo terminó de importar.
    
7. _Concurrente al inicio:_ Módulos que requieran configuración importan `config/settings.py`, el cual lee/valida `app_config.json`.
    
8. Precarga lista → se guarda en `DataManager.guardar_precarga_principal`.
    
9. Animación terminada → construye `MainWindow()` (su `load_data_async` usa la precarga), la muestra y cierra el splash con un fundido. `app.exec()` ya estaba corriendo desde el paso 5.
    

### 8. Dependencias que debemos investigar después

- **`src/ui/main_window.py`** ([[03_Vistas_y_Navegacion_UI]]): Es la carga principal en el tick 75 del splash. Dependemos de auditar este archivo para saber si su inicialización retrasa la animación o si realmente delega el trabajo pesado a otros hilos.
    

### 9. Observaciones/riesgos (Solo reporte)

- **Código duplicado inalcanzable (Dead Code) — CORREGIDO 03-09-2026:** En `main.py` se repetía exactamente el mismo bloque de código para la creación del ícono, Splash Screen y `sys.exit()` después del primer `sys.exit(app.exec())` de `main()`, por lo que jamás se ejecutaba. Fue eliminado. De paso se corrigió un `datetime.now()` (debía ser `datetime.datetime.now()`, dado que el módulo se importa con `import datetime`) en el manejo de errores fatales de arranque, que fallaba en silencio e impedía escribir el detalle del error en `logs/sistema.log`. Detalle en [[01_Arranque_y_Configuracion]] §8.1.
    
- **Simulación visual vs Carga real (actualizado 01-10-2026):** Los textos de estado del splash ("Cargando motor de datos...", etc.) siguen el avance visual de la barra y son cosméticos. Si la lectura real tarda más que la animación, la barra se queda en 95 % con "Esperando datos..." hasta que termina. Ver [[01_Arranque_y_Configuracion]] §8.2.
    
- **Fragilidad de Configuración:** La discrepancia entre la llave `"POWERBI_URL"` en `DEFAULT_CONFIG` y el uso de `.get("POWERBI_EMBED_URL")` provoca que, si el archivo JSON se llegara a borrar o corromper, la recreación automática mediante el diccionario por defecto no incluirá la llave correcta que requiere el sistema.
    

### 10. Archivos que recomiendas analizar como siguiente paso y por qué

Recomiendo solicitar a la IA que analice en la próxima fase:

1. **`src/ui/main_window.py`** ([[03_Vistas_y_Navegacion_UI]]): Es el archivo más crítico ahora mismo. Necesitamos auditar qué procesos dispara en su `__init__` para comprender exactamente cuánto peso de procesamiento asume el sistema antes de que el usuario vea la primera pantalla.
    
2. **`src/core/data_manager.py`** ([[02_Motor_de_Datos_Core]]): `ARCHITECTURE.md` lo define como el núcleo que levanta los hilos de lectura. Necesitamos verificar cuándo y cómo `MainWindow` (o el flujo de arranque) invoca a este administrador de memoria.

---

## Documentos relacionados

- [[01_Arranque_y_Configuracion]] — versión narrativa/consolidada de este mismo tema (arranque y configuración)
- [[02_Motor_de_Datos_Core]] — DataManager, pendiente de auditoría según este documento
- [[03_Vistas_y_Navegacion_UI]] — MainWindow, pendiente de auditoría según este documento
- [[04. Arquitectura y Patrones del Sistema]] — síntesis arquitectónica que conecta todos los documentos técnicos (02, 03, 05, 06, 07)
- [[08. Arquitectura Visual y Diagramas]] — capa visual (diagramas Mermaid) sobre la arquitectura general y el flujo de arranque
- [[09. Despliegue y Onboarding]] — cómo instalar, configurar y ejecutar la aplicación en un equipo nuevo
- [[12. Rendimiento y Optimizaciones de Interfaz]] — historial técnico de rendimiento, sin relación directa con el arranque descrito aquí
- [[10. Manual de Operación]] — guía de uso orientada a usuarios de negocio, sin lenguaje técnico