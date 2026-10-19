# Gestor SSCC — Documentación

Este es el Vault de Obsidian con la documentación técnica y funcional de **Gestor SSCC** (antes Gestor SSCC; la carpeta del proyecto sigue llamándose `empresa_dashboard_app`), una aplicación de escritorio en PyQt6 que centraliza la gestión de la flota comercial (contratos, provisiones financieras, contactos, instalaciones, contratos de mantenimiento y correos) sobre archivos Excel como fuente de datos.

Este README es solo un mapa de navegación. No repite conocimiento técnico — cada tema vive en un único documento; si necesitas el detalle, entra al documento correspondiente en vez de buscarlo aquí.

## Cómo está organizada esta documentación

El código (`main.py`, `config/`, `src/`) es siempre la fuente de verdad sobre el comportamiento real del sistema. Estos documentos registran el estado auditado del código en la fecha de su última actualización; si algo aquí contradice al código actual, el código gana. Ver `CLAUDE.md` (raíz del proyecto) para las reglas completas de cómo se mantiene este Vault.

`docs/00_Indice_Principal.md` **no es un índice** pese a su nombre — contiene información de arranque/configuración (mismo tema que el documento 01, en formato de auditoría/hallazgos). Usa este README como punto de entrada real.

## Documentos

**Arranque y configuración**
- [[00_Indice_Principal]] — versión en formato de auditoría/hallazgos del arranque (ver nota arriba)
- [[01_Arranque_y_Configuracion]] — versión narrativa: `main.py`, `config/settings.py`, `app_config.json`

**Núcleo técnico**
- [[02_Motor_de_Datos_Core]] — `DataManager`, `ExcelReader`, `ExcelWriter`, `FileWatcher`, `DataFrameFormatter`, servicios de correo
- [[03_Vistas_y_Navegacion_UI]] — `MainWindow` y los módulos de `src/ui/`
- [[04. Arquitectura y Patrones del Sistema]] — síntesis arquitectónica (patrones, capas, deuda técnica)

**Flujos y reglas**
- [[05. Flujos de Datos y Sincronización]] — carga/escritura, ETLs internos, SharePoint, RM_CONTRATOS, Instalaciones, Correos
- [[06. Seguridad, Integridad y Resiliencia de Datos]] — backups, archivos temporales, watchdog, tolerancia a fallos
- [[07. Procesos y Reglas de Negocio]] — reglas y cálculos por módulo

**Visual, despliegue y operación**
- [[08. Arquitectura Visual y Diagramas]] — diagramas Mermaid de lo descrito en los documentos anteriores
- [[09. Despliegue y Onboarding]] — cómo instalar, configurar, ejecutar y compilar el proyecto
- [[10. Manual de Operación]] — guía de uso en lenguaje de negocio, sin jerga técnica
- [[11. Pruebas y Auditoría de Tests]] — estructura de `src/tests/`, cómo se ejecutan y el auditor automático (`src/tests/auditor/`); su lista de archivos/conteos se desactualiza con cada test nuevo, ver advertencia en §1
- [[12. Rendimiento y Optimizaciones de Interfaz]] — historial técnico de la auditoría de rendimiento de UI (debounce, cachés, `GeneralDataPrepThread`, render diferido) y de las optimizaciones anteriores a ella
- [[13. Matriz de Requerimientos y Trazabilidad]] — lista de requerimientos de negocio y matriz de trazabilidad código↔requerimiento (RG-01 a RG-43)
- [[14. Guía de General, Comercial y Operaciones]] — qué hace cada una de las tres pantallas centrales, quién las usa y cómo se trabaja (en Operaciones, primero Servicios Conectados y luego el registro en la app)
- [[15. Guía de Ingresos y Conciliación]] — qué son Provisiones, Contratos (CM), Facturación Manual y JustTime, quién las usa y cómo se trabaja

[[ARCHITECTURE]] (documento previo del 29-08-2026, movido a esta carpeta el 13-10-2026) es más general y está parcialmente desactualizado; en caso de conflicto, el resto de este Vault prevalece por ser la auditoría más reciente.
