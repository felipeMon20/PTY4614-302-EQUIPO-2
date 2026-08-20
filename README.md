# Volvo Dashboard - Plataforma de Gestion Unificada (Servicios Conectados)

**Autor Principal:** Felipe Monsalve Umanzor (Desarrollador Full-Stack)
**Documentacion (Duoc UC):** Irma Beltran
**Product Owner:** Javiera Gonzalez (Encargada Servicios Conectados, Volvo Chile SPA)

## 1. Vision General del Proyecto
El Volvo Dashboard es una aplicacion de escritorio nativa de grado empresarial desarrollada en Python y PyQt6. 
Su objetivo es centralizar, visualizar y automatizar la gestion de grandes volumenes de datos operativos, comerciales y financieros para 
el area de Servicios Conectados de Volvo Chile SPA

Dada la restriccion corporativa de ciberseguridad que prohibe el despliegue de bases de datos relacionales (SQL), 
la plataforma opera utilizando una arquitectura basada en archivos Excel (Single Source of Truth) 
alojados y sincronizados en la nube mediante SharePoint y OneDrive

## 2. Arquitectura del Sistema
El software esta construido sobre el patron de diseño MVC (Modelo-Vista-Controlador), garantizando el desacoplamiento entre la capa de presentacion visual y el procesamiento logico de datos.

* **Motor Grafico (UI):** PyQt6 con inyeccion de estilos centralizada (ThemeManager) y renderizado adaptativo (Lazy Loading).
* **Procesamiento de Datos (Core):** Pandas para procesos ETL (Extraccion, Transformacion y Carga) en memoria RAM.
* **Motor Transaccional:** OpenPyXL para operaciones de escritura quirurgica a nivel de celda sin alterar los formatos originales del libro matriz.
* **Monitoreo de Red:** Libreria Watchdog con algoritmos mitigadores de rebote (Debounce) para detectar modificaciones externas y prevenir colisiones de red.

## 3. Funcionalidades Principales (Core Features)
El desarrollo cubre un conjunto estricto de requerimientos funcionales (RF) y no funcionales (RNF):

* **Inyeccion Atomica y Evasion de Bloqueos:** Implementacion de "Ghost Files" (archivos temporales locales) para realizar sobreescrituras en fracciones de segundo, burlando los bloqueos nativos de SharePoint y previniendo la corrupcion de datos.
* **Concurrencia Asincrona (QThread):** Desacoplamiento total de procesos pesados de lectura/escritura del hilo principal de la interfaz, asegurando una experiencia de usuario fluida a 60 FPS.
* **Sistema de Auto-Sanacion:** Algoritmos de limpieza automatica (drop_duplicates) ejecutados sobre llaves unicas (VIN_CLEAN) para erradicar el efecto multiplicador de registros.
* **Inteligencia de Negocios (BI):** Módulo directivo renderizado con Matplotlib, incluyendo dashboards gerenciales de rentabilidad (VAR), proyecciones de vencimientos y alertas operativas con filtrado cruzado interactivo.
* **Auditoria y Trazabilidad Diferencial:** Registro automatico de logs transaccionales capturando el estado anterior y nuevo de cada celda modificada, almacenado con marca de tiempo y paginacion de alto rendimiento.

## 4. Modulos del Sistema
* **General:** Centro de mando interactivo con visualizacion de KPIs financieros y operativos.
* **Comercial:** Administracion y seguimiento de flota con autocompletado inteligente y calculo de parametros de contratos.
* **Provisiones:** Motor financiero con automatizacion de cobros y obtencion del valor dinamico de la UF.
* **Instalaciones:** Motor ETL en segundo plano para la automatizacion, cruce y exportacion de reportes mensuales.
* **Contactos & Envios:** Directorio cruzado para seguimiento y proxima implementacion de notificaciones masivas.
* **Historial & Papelera:** Entorno seguro para restauracion de backups, reversion de filas eliminadas y vaciado seguro de auditorias.

## 5. Estado Actual del Proyecto
* **Version:** 1.0 (QA y estabilizacion finalizada).
* **Entorno:** Operativo mediante binario compilado (.exe) independiente, optimizado para Windows 11.
