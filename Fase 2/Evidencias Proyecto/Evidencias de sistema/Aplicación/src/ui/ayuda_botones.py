"""Ayuda de Configuración: qué hace cada botón de cada pantalla y cuándo usarlo."""
import qtawesome as qta
from PyQt6 import sip
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from src.theme import tema
from src.ui import comercial_estilo as estilo_com

_SIN_FONDO = "border: none; background: transparent;"
_VOLVO = "#1B2B4E"
_VOLVO_SUAVE = "#E6ECF6"

# (pantalla, ícono, [(botón, ícono del botón, qué hace, cuándo se usa)]). El ícono del
# botón es el mismo que tiene en la pantalla.
AYUDA = [
    ("Dashboard", 'fa5s.chart-pie', [
        ("Filtros de la barra", 'fa5s.filter',
         "Ejecutivo, contrato, plan (con las casillas CIV y SZ), año y mes de inicio de contrato. Se combinan: cada uno ofrece solo lo compatible con los demás.",
         "Para ver cómo le va a una parte del negocio."),
        ("Mes (varios meses)", 'fa5s.calendar-alt', "Permite marcar varios meses: los gráficos mensuales muestran solo esos.", "Para comparar meses concretos."),
        ("Pruebas", 'fa5s.flask', "Incluye los contratos de prueba (Test y Demo), que por defecto quedan fuera de las cifras.",
         "Cuando quieres ver todo, incluidas las pruebas."),
        ("Quitar filtros", 'fa5s.times', "Quita todos los filtros elegidos.", "Para volver a ver el negocio completo."),
        ("Metas", 'fa5s.bullseye', "Abre el panel para fijar la meta de unidades vendidas de un mes. Los meses pasados no se pueden cambiar.",
         "Al comienzo de cada mes."),
        ("Ver 6 meses más / Ver menos", 'fa5s.expand-arrows-alt', "Amplía o acorta el gráfico de unidades vendidas a 6 o 12 meses.",
         "Para comparar un periodo más largo."),
        ("Industria / Modelo / Facturación", 'fa5s.industry', "Cambian el grupo con que se mide dónde se pierden clientes.",
         "Para ver qué tipo de cliente se pierde más."),
        ("Más desconectadas / Solo parciales", 'fa5s.user-slash',
         "Cambian la lista de clientes a recuperar: los que más unidades perdieron o los que aún conservan unidades conectadas.",
         "Para decidir a quién llamar primero."),
    ]),
    ("Comercial: barra superior", 'fa5s.handshake', [
        ("BI", 'fa5s.chart-bar', "Abre el reporte de Notas de Venta en Power BI en el navegador.",
         "Para consultar una nota de venta filtrando por los últimos 7 dígitos del chasis."),
        ("Filtros por columna", 'fa5s.filter',
         "Periodo interno, forma de contrato, tipo de facturación y tipo de servicio. Se combinan: cada filtro ofrece solo lo compatible con los demás.",
         "Para acotar la bandeja a un grupo de unidades."),
        ("Excel", 'fa5s.file-excel', "Guarda en un Excel la tabla tal como la ves, con los filtros aplicados.",
         "Para enviar o revisar la lista fuera de la aplicación."),
        ("Revisar inconsistencias", 'fa5s.clipboard-check',
         "Filtra las unidades cuya forma de contrato y tipo de facturación no cumplen la matriz. No corrige nada.",
         "Para detectar datos mal clasificados antes de que Operaciones o JustTime los usen."),
        ("Revisar fechas", 'fa5s.not-equal', "Muestra los contratos cuyo término en el archivo no coincide con inicio + duración.",
         "Para corregir el Registro Maestro; la aplicación ya usa el término calculado."),
        ("Quitar filtros", 'fa5s.trash-alt', "Quita todos los filtros elegidos de la bandeja.",
         "Aparece cuando hay algún filtro elegido, para volver a ver toda la lista."),
        ("Arreglar (número)", 'fa5s.magic',
         "Corrige de una vez el tipo de facturación de todas las unidades que se pueden arreglar. El número indica cuántas son.",
         "Cuando aparece el botón, antes de revisar una por una."),
        ("Arreglar fechas (número)", 'fa5s.magic',
         "Corrige el término de los contratos cuyo término en el archivo no coincide con inicio + duración.",
         "Cuando aparece el botón, para dejar el archivo igual a lo que muestra la aplicación."),
        ("Marcar vencidos (número)", 'fa5s.calendar-times',
         "Marca como Vencido todas las unidades con término pasado que siguen Vigente o en Activación Pendiente.",
         "Para ordenar la cartera de una vez; el número indica cuántas son."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los archivos de datos.", "Cuando otra persona cambió el archivo y no ves lo nuevo."),
        ("Ampliar", 'fa5s.expand', "Oculta las tarjetas de resumen para que la tabla ocupe más espacio.",
         "Cuando necesitas ver más filas a la vez."),
    ]),
    ("Comercial: acciones rápidas", 'fa5s.bolt', [
        ("Enviar correo", 'fa5s.envelope', "Abre el gestor de correos con la unidad seleccionada.", "Para contactar al cliente por una unidad o contrato."),
        ("Editar contrato", 'fa5s.file-contract', "Abre el formulario del contrato para modificar sus datos.",
         "Para corregir o completar datos. En Renovar contratos, la forma de contrato queda bloqueada."),
        ("Ver en General", 'fa5s.search', "Salta a General con esa unidad abierta.", "Para ver la ficha completa y los contratos anteriores."),
        ("Crear contrato", 'fa5s.file-signature', "Abre un contrato nuevo con los datos de la unidad y del cliente.",
         "Cuando una unidad cuyo contrato ya cerró vuelve con el cliente."),
        ("Agregar contacto", 'fa5s.user-plus', "Registra un contacto de la empresa de la unidad.", "Cuando falta el correo o teléfono de alguien."),
        ("Enviar a operaciones", 'fa5s.bolt', "Deriva la unidad a Operaciones.",
         "Cuando Operaciones debe conectarla, desconectarla o gestionar su baja."),
        ("Marcar como Vencido", 'fa5s.calendar-times', "Pone en Vencido los contratos cuya fecha de término ya pasó y siguen con otro estado.",
         "Para ordenar la bandeja Renovar contratos."),
        ("Marcar como Vigente", 'fa5s.check-circle', "Pasa a Vigente las unidades Conectadas que están en Activación Pendiente, y los contratos MENSUAL en Vencido (un mensual no vence por fecha).",
         "Cuando Operaciones ya conectó la unidad y el estado comercial quedó atrasado."),
        ("Extender duración", 'fa5s.redo-alt',
         "Suma meses a la duración de los contratos elegidos y recalcula el término. Opcionalmente cambia el inicio de todos.",
         "Para alargar un contrato que sigue igual. Un contrato Vencido vuelve a Vigente."),
        ("Renovar contrato", 'fa5s.file-contract', "Crea un contrato nuevo para la misma unidad y deja el actual como Renovado.",
         "Cuando cambia la forma de contrato, por ejemplo de Provisión a Conversión. Una unidad a la vez."),
        ("Exportar lista (Gestionar CM)", 'fa5s.file-export', "Guarda en el Escritorio la bandeja de CM que ves.",
         "Para avisar a quien administra los contratos de mantenimiento."),
        ("Confirmar baja (Gestionar CM)", 'fa5s.check-circle', "Cierra el caso, da de baja el contrato y lo envía a Operaciones para desconectar.", "Solo para casos de Ausencia de 3PC."),
        ("Enviar a papelera", 'fa5s.trash-alt', "Manda a la papelera los contratos SIN VC seleccionados.",
         "Para descartar oportunidades que no quisieron o no respondieron al servicio."),
        ("Arreglar tipo de facturación", 'fa5s.magic', "Corrige el tipo de facturación según la forma de contrato.",
         "Cuando el aviso muestra combinaciones inválidas con una sola opción correcta."),
        ("Fecha real", 'fa5s.calendar-check', "Graba en el archivo el término calculado (inicio + duración).",
         "Para dejar el archivo igual a lo que muestra la aplicación."),
    ]),
    ("Operaciones", 'fa5s.shipping-fast', [
        ("Conectado", 'fa5s.check-circle', "Marca como CONECTADO las unidades seleccionadas y su estado comercial pasa a Vigente. Exige CDB flota y Flota VC.",
         "Cuando la unidad ya aparece en Volvo Connect. Si estaba en Activación Pendiente, pide la fecha de activación."),
        ("Sin flota", 'fa5s.truck-loading', "Saca la unidad de Activaciones porque todavía no aparece en Volvo Connect.",
         "Cuando no se pudo encontrar la unidad en Volvo Connect."),
        ("Desconectado", 'fa5s.unlink', "Confirma la baja con la fecha de hoy.", "En la pestaña Bajas, cuando la unidad ya se desconectó."),
        ("Guardar flota", 'fa5s.save', "Guarda la Flota VC y el CDB flota escritos en el panel, sin cambiar el estado.",
         "Para corregir datos de flota de unidades de una misma empresa."),
        ("Limpiar flota", 'fa5s.eraser', "Deja Flota VC y CDB flota en \"-\" en todas las unidades seleccionadas, sean o no de la misma empresa.",
         "En Sin Flota, para borrar datos de flota incompletos o equivocados."),
        ("Contactar ejecutivo", 'fa5s.envelope', "Abre un borrador en Outlook para el ejecutivo de la unidad.",
         "Para consultar o avisar algo sobre la unidad."),
        ("Exportar VIN & CDB", 'fa5s.file-excel', "Guarda en el Escritorio un Excel con VIN, CDB flota y plan de la tabla.",
         "Para cargar o cruzar unidades en Volvo Connect. Exporta solo las filas seleccionadas si hay."),
        ("Exportar contactos", 'fa5s.file-export', "Genera un Excel con los contactos de los clientes de Activaciones.", "Para dárselo al ejecutivo."),
        ("Filtros de la barra", 'fa5s.user-tie',
         "Cliente, forma de contrato y tipo de servicio. Se combinan: cada uno ofrece solo lo compatible con los demás.",
         "Para trabajar de a un cliente o un tipo de contrato."),
        ("Quitar filtros", 'fa5s.trash-alt', "Quita los filtros elegidos.", "Para volver a ver todas las unidades de la pestaña."),
        ("Ampliar tabla", 'fa5s.expand', "Oculta las tarjetas de resumen para que la tabla ocupe más espacio.",
         "Cuando necesitas ver más filas a la vez."),
        ("Power BI", 'fa5s.chart-bar', "Abre el reporte de Notas de Venta en Power BI en el navegador.",
         "Para consultar una nota de venta de la unidad."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los archivos de datos.", "Cuando otra persona cambió el archivo y no ves lo nuevo."),
        ("Triángulo (Conectados)", 'fa5s.exclamation-triangle', "Muestra solo las unidades sin Flota VC o sin CDB flota.",
         "Para completar los datos pendientes."),
        ("Rama roja (Conectados)", 'fa5s.code-branch', "Muestra los CDB flota que tienen más de una Flota VC.",
         "Para detectar y corregir esos CDB."),
    ]),
    ("Clientes y Flota", 'fa5s.building', [
        ("Mostrar (cantidad)", 'fa5s.list-ol', "Elige cuántas filas se muestran por página.", "Cuando la lista es muy larga o muy corta para ti."),
        ("Ordenar", 'fa5s.sort-alpha-down', "Cambia el orden de la lista.", "Para encontrar más rápido lo que buscas."),
        ("Anterior / Siguiente", 'fa5s.arrows-alt-h', "Pasan de una página de la lista a otra.", "Cuando hay más filas que las mostradas."),
        ("Cliente / Unidades", 'fa5s.building', "Cambia la lista de la izquierda entre clientes y unidades.", "Según si buscas por empresa o por camión."),
        ("Filtros / Limpiar filtros", 'fa5s.filter', "Abre los filtros de la lista de unidades y los quita todos.", "Para acotar la búsqueda."),
        ("Solo con aviso de flotas", 'fa5s.check-square', "Deja en la lista solo los clientes con el aviso amarillo de flotas.",
         "Para revisar y corregir los clientes con flotas incoherentes."),
        ("Resumen, Unidades, Flotas VC, Contactos, Razones", 'fa5s.columns', "Cambian el detalle que ves del cliente elegido.",
         "Para revisar cada aspecto del cliente."),
        ("Aviso amarillo en un cliente", 'fa5s.exclamation-circle',
         "Indica flotas incoherentes: CDB con varias flotas, flotas con varios CDB o unidades con un solo dato.",
         "Pasa el mouse para ver el detalle y corrígelo en Operaciones."),
        ("Ficha / Historial / Contratos anteriores", 'fa5s.id-card', "Muestran la unidad, sus cambios y los contratos que tuvo.",
         "Para entender qué le pasó a una unidad."),
        ("Ver contrato actual", 'fa5s.arrow-left', "Vuelve del historial al contrato vigente.", "Después de mirar contratos anteriores."),
        ("Contactar", 'fa5s.envelope', "Abre el correo hacia el cliente.", "Para escribirle desde la ficha."),
        ("Agregar contacto", 'fa5s.user-plus', "Registra un contacto del cliente.", "Cuando falta alguien en el directorio."),
        ("Unificar en una sola razón social", 'fa5s.compress-arrows-alt', "Deja una única razón social para un RUT que tiene varias.",
         "Cuando es la misma empresa escrita distinto."),
    ]),
    ("Provisiones", 'fa5s.piggy-bank', [
        ("Mes / Plan", 'fa5s.calendar-alt', "Filtran la lista por mes y por plan.", "Para revisar un periodo."),
        ("Descartar", 'fa5s.undo', "Deshace los cambios sin guardar.", "Si te equivocaste antes de guardar."),
        ("Guardar", 'fa5s.save', "Guarda los cambios hechos en la lista.", "Después de editar."),
        ("Excel", 'fa5s.file-excel', "Exporta la lista a Excel.", "Para revisar o compartir."),
        ("Copiar VIN", 'fa5s.copy', "Copia los VIN del mes y plan filtrados.", "Para pegarlos en la búsqueda de otra pantalla."),
        ("+", 'fa5s.plus', "Abre la sincronización con SharePoint.", "Para traer un archivo nuevo de provisiones."),
        ("Engranaje", 'fa5s.cog', "Abre los ajustes de costos.", "Cuando cambian los valores del plan."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los datos.", "Si otra persona los cambió."),
        ("Editar provisión", 'fa5s.edit', "Abre el formulario del registro: Dynafleet, cantidad de meses y plan.", "Para corregir una provisión."),
    ]),
    ("Contratos (CM)", 'fa5s.file-signature', [
        ("Estado del CM / Tipo de CM", 'fa5s.flag', "Filtran la lista de contratos de mantenimiento.", "Para ver solo un estado o tipo."),
        ("Ampliar tabla", 'fa5s.expand', "Oculta las tarjetas de resumen para que la tabla ocupe más espacio.", "Cuando necesitas ver más filas a la vez."),
        ("+", 'fa5s.plus', "Importa el Excel de contratos CM.", "Cuando llega un archivo nuevo."),
        ("Excel", 'fa5s.file-excel', "Exporta la lista a Excel.", "Para revisar o compartir."),
        ("Borrador", 'fa5s.eraser', "Deja en \"-\" los datos de CM de unidades que no son de CM.", "Para limpiar datos que sobran."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los datos.", "Si otra persona los cambió."),
        ("Editar unidad", 'fa5s.edit', "Abre el formulario en la pestaña JustTime & CM.", "Para corregir los datos de CM."),
    ]),
    ("Facturación Manual", 'fa5s.file-invoice-dollar', [
        ("Ampliar tabla", 'fa5s.expand', "Oculta las tarjetas de resumen para que la tabla ocupe más espacio.", "Cuando necesitas ver más filas a la vez."),
        ("Excel (lista)", 'fa5s.file-excel', "Exporta la lista de empresas a Excel.", "Para ver el estado de la facturación del mes."),
        ("$", 'fa5s.dollar-sign', "Busca la UF de hoy en internet y la guarda en Variables.", "Al empezar a facturar el día, para usar el valor correcto."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los datos.", "Si otra persona los cambió."),
        ("Abrir editor", 'fa5s.edit', "Abre la empresa: revisa la flota, define el precio UF y genera el PDF.", "Para preparar la factura de una empresa."),
        ("Marcar como Facturado / Pendiente", 'fa5s.check-circle', "Cambia la etapa de las empresas seleccionadas.", "Al terminar de facturar o para reabrir."),
        ("Exportar a PDF / Excel (editor)", 'fa5s.file-pdf', "Genera el detalle de la factura de la empresa en ese formato.", "Para enviarlo o respaldarlo."),
    ]),
    ("JustTime", 'fa5s.stopwatch', [
        ("Estado", 'fa5s.filter', "Filtra por estado en JustTime.", "Para ver pendientes o eliminar."),
        ("Ampliar tabla", 'fa5s.expand', "Oculta las tarjetas de resumen para que la tabla ocupe más espacio.", "Cuando necesitas ver más filas a la vez."),
        ("Excel", 'fa5s.file-excel', "Exporta las unidades filtradas.", "Para revisar o compartir."),
        ("Cambiar estado", 'fa5s.exchange-alt', "Cambia el estado de todas las unidades que se muestran.", "Para actualizar un grupo completo."),
        ("Arreglar fechas", 'fa5s.calendar-check', "Lleva el inicio al primer día del mes y recalcula el término.", "Cuando las fechas de JustTime no coinciden."),
        ("Recargar", 'fa5s.sync-alt', "Vuelve a leer los datos.", "Si otra persona los cambió."),
        ("Corregir según matriz", 'fa5s.broom', "Deja las unidades seleccionadas con el estado que les corresponde.",
         "Cuando el estado no calza con el tipo de facturación."),
        ("Aplicar sugerencia", 'fa5s.magic', "Pasa las unidades con formato antiguo al estado sugerido.", "Para ordenar datos antiguos."),
        ("Limpiar datos", 'fa5s.eraser', "Deja en \"-\" estado, inicio y término de unidades que no van a JustTime.", "Cuando ya salieron de JustTime."),
    ]),
    ("Correos", 'fa5s.envelope', [
        ("Sincronizar BBDD Correos", 'fa5s.database', "Reconstruye Correos.csv cruzando Comercial con Contactos.", "Cuando faltan unidades o correos."),
        ("Registro", 'fa5s.history', "Muestra los correos enviados.", "Para saber si ya se avisó a un cliente."),
        ("Botones de plantilla", 'fa5s.file-alt', "Cargan el texto del correo elegido.", "Según el motivo: bienvenida, activación, vencimiento, etc."),
        ("Abrir en Outlook", 'fa5s.external-link-alt', "Crea el borrador en Outlook con los destinatarios marcados.", "Cuando el texto está listo."),
        ("Por vencer", 'fa5s.calendar-alt', "Muestra las mismas unidades que Por vencer en Comercial.", "Para el aviso de vencimiento."),
    ]),
    ("Administración", 'fa5s.archive', [
        ("Historial: Eliminar registros antiguos", 'fa5s.trash-alt',
         "Elimina los registros del historial de modificaciones con más de 30 días, con respaldo previo.", "Solo para limpiar el historial."),
        ("Historial: Mostrar 10 días más", 'fa5s.history', "Trae 10 días más de historial a la lista.", "Cuando buscas un cambio más antiguo."),
        ("Instalaciones: Generar mes", 'fa5s.cogs', "Abre la sincronización para crear la hoja del mes.", "Al empezar un mes nuevo."),
        ("Instalaciones: Renombrar / Eliminar hoja", 'fa5s.edit', "Cambia el nombre o borra la hoja actual.", "Para corregir hojas del archivo."),
        ("Contactos: Agregar / Importar", 'fa5s.plus', "Agrega un contacto o trae los nuevos del Excel del bot de Volvo Connect.", "Para mantener el directorio al día."),
        ("Contactos: Corregir teléfonos", 'fa5s.magic', "Arregla al formato +56 9 XXXX XXXX los números que se pueden corregir solos.", "Después de importar."),
        ("Contactos: Guardar cambios", 'fa5s.save', "Guarda las ediciones hechas en la tabla.", "Después de editar."),
        ("Ejecutivos: Agregar / Editar / Desactivar", 'fa5s.user-tie', "Gestiona el directorio de ejecutivos.", "Cuando alguien entra, cambia o se va."),
        ("Excel / Recargar", 'fa5s.file-excel', "Exportan la lista o vuelven a leer los datos.", "En todas las pantallas de Administración."),
    ]),
    ("Configuración", 'fa5s.cog', [
        ("Guardar y reiniciar", 'fa5s.save', "Guarda las rutas y los enlaces y reinicia la aplicación.", "Después de cambiar la carpeta de datos o un enlace."),
        ("Examinar", 'fa5s.folder-open', "Te deja elegir a mano la carpeta que contiene los archivos de datos.", "Cuando la detección automática no la encuentra."),
        ("Autodetectar", 'fa5s.magic', "Busca sola la carpeta de datos y completa las rutas de todos los archivos.", "La primera vez, o si cambió la carpeta."),
        ("Abrir carpeta", 'fa5s.external-link-alt', "Abre la carpeta de datos en el explorador de archivos.", "Para revisar o copiar un archivo a mano."),
        ("¿Cómo me conecto?", 'fa5s.question-circle', "Explica paso a paso cómo conectar la carpeta compartida de datos.", "Si es la primera vez o no ves los archivos."),
        ("Actualizar copia de BBDD Clientes CM", 'fa5s.file-upload', "Reemplaza la copia local de BBDD Clientes CM por otro archivo.", "Cuando llega una versión nueva del Excel."),
        ("Editar (Enlaces)", 'fa5s.pen', "Permite cambiar una dirección de SharePoint o Power BI.", "Solo si cambió el enlace."),
    ]),
]

# Categorías de la ayuda y su ícono
CATEGORIAS = ("Ver y filtrar", "Cambiar estado", "Editar y corregir", "Comunicar", "Exportar y compartir", "Actualizar datos")
_ICONO_CATEGORIA = {'Ver y filtrar': 'fa5s.filter', 'Cambiar estado': 'fa5s.exchange-alt', 'Editar y corregir': 'fa5s.edit',
                    'Comunicar': 'fa5s.envelope', 'Exportar y compartir': 'fa5s.share-square', 'Actualizar datos': 'fa5s.sync-alt'}
_V, _CE, _E, _C, _X, _A = CATEGORIAS

# (pantalla, botón) -> categoría
CATEGORIA_BOTON = {
    ('Dashboard', 'Filtros de la barra'): _V, ('Dashboard', 'Mes (varios meses)'): _V, ('Dashboard', 'Pruebas'): _V,
    ('Dashboard', 'Quitar filtros'): _V, ('Dashboard', 'Metas'): _E, ('Dashboard', 'Ver 6 meses más / Ver menos'): _V,
    ('Dashboard', 'Industria / Modelo / Facturación'): _V, ('Dashboard', 'Más desconectadas / Solo parciales'): _V,
    ('Comercial: barra superior', 'BI'): _V, ('Comercial: barra superior', 'Filtros por columna'): _V, ('Comercial: barra superior', 'Ampliar'): _V, ('Comercial: barra superior', 'Quitar filtros'): _V,
    ('Comercial: barra superior', 'Excel'): _X,
    ('Comercial: barra superior', 'Revisar inconsistencias'): _V, ('Comercial: barra superior', 'Revisar fechas'): _V,
    ('Comercial: barra superior', 'Arreglar (número)'): _E, ('Comercial: barra superior', 'Arreglar fechas (número)'): _E,
    ('Comercial: barra superior', 'Marcar vencidos (número)'): _CE, ('Comercial: barra superior', 'Recargar'): _A,
    ('Comercial: acciones rápidas', 'Enviar correo'): _C, ('Comercial: acciones rápidas', 'Editar contrato'): _E,
    ('Comercial: acciones rápidas', 'Ver en General'): _V, ('Comercial: acciones rápidas', 'Crear contrato'): _E,
    ('Comercial: acciones rápidas', 'Agregar contacto'): _C, ('Comercial: acciones rápidas', 'Enviar a operaciones'): _CE,
    ('Comercial: acciones rápidas', 'Marcar como Vencido'): _CE, ('Comercial: acciones rápidas', 'Marcar como Vigente'): _CE,
    ('Comercial: acciones rápidas', 'Extender duración'): _E, ('Comercial: acciones rápidas', 'Renovar contrato'): _CE,
    ('Comercial: acciones rápidas', 'Exportar lista (Gestionar CM)'): _X, ('Comercial: acciones rápidas', 'Confirmar baja (Gestionar CM)'): _CE,
    ('Comercial: acciones rápidas', 'Enviar a papelera'): _CE,
    ('Comercial: acciones rápidas', 'Arreglar tipo de facturación'): _E, ('Comercial: acciones rápidas', 'Fecha real'): _E,
    ('Operaciones', 'Conectado'): _CE, ('Operaciones', 'Sin flota'): _CE, ('Operaciones', 'Desconectado'): _CE,
    ('Operaciones', 'Guardar flota'): _E, ('Operaciones', 'Limpiar flota'): _E, ('Operaciones', 'Contactar ejecutivo'): _C,
    ('Operaciones', 'Exportar VIN & CDB'): _X, ('Operaciones', 'Exportar contactos'): _X, ('Operaciones', 'Filtros de la barra'): _V,
    ('Operaciones', 'Quitar filtros'): _V, ('Operaciones', 'Ampliar tabla'): _V, ('Operaciones', 'Power BI'): _V,
    ('Operaciones', 'Recargar'): _A, ('Operaciones', 'Triángulo (Conectados)'): _V, ('Operaciones', 'Rama roja (Conectados)'): _V,
    ('Clientes y Flota', 'Mostrar (cantidad)'): _V, ('Clientes y Flota', 'Ordenar'): _V, ('Clientes y Flota', 'Anterior / Siguiente'): _V,
    ('Clientes y Flota', 'Cliente / Unidades'): _V, ('Clientes y Flota', 'Filtros / Limpiar filtros'): _V, ('Clientes y Flota', 'Solo con aviso de flotas'): _V,
    ('Clientes y Flota', 'Resumen, Unidades, Flotas VC, Contactos, Razones'): _V, ('Clientes y Flota', 'Aviso amarillo en un cliente'): _V,
    ('Clientes y Flota', 'Ficha / Historial / Contratos anteriores'): _V, ('Clientes y Flota', 'Ver contrato actual'): _V, ('Clientes y Flota', 'Contactar'): _C,
    ('Clientes y Flota', 'Agregar contacto'): _C, ('Clientes y Flota', 'Unificar en una sola razón social'): _E,
    ('Provisiones', 'Mes / Plan'): _V, ('Provisiones', 'Descartar'): _E, ('Provisiones', 'Guardar'): _E, ('Provisiones', 'Excel'): _X,
    ('Provisiones', 'Copiar VIN'): _X, ('Provisiones', '+'): _A, ('Provisiones', 'Engranaje'): _E, ('Provisiones', 'Recargar'): _A,
    ('Provisiones', 'Editar provisión'): _E,
    ('Contratos (CM)', 'Estado del CM / Tipo de CM'): _V, ('Contratos (CM)', 'Ampliar tabla'): _V, ('Contratos (CM)', '+'): _A, ('Contratos (CM)', 'Excel'): _X,
    ('Contratos (CM)', 'Borrador'): _E, ('Contratos (CM)', 'Recargar'): _A, ('Contratos (CM)', 'Editar unidad'): _E,
    ('Facturación Manual', 'Excel (lista)'): _X, ('Facturación Manual', 'Ampliar tabla'): _V, ('Facturación Manual', '$'): _A, ('Facturación Manual', 'Recargar'): _A,
    ('Facturación Manual', 'Abrir editor'): _E, ('Facturación Manual', 'Marcar como Facturado / Pendiente'): _CE,
    ('Facturación Manual', 'Exportar a PDF / Excel (editor)'): _X,
    ('JustTime', 'Estado'): _V, ('JustTime', 'Ampliar tabla'): _V, ('JustTime', 'Excel'): _X, ('JustTime', 'Cambiar estado'): _CE, ('JustTime', 'Arreglar fechas'): _E,
    ('JustTime', 'Recargar'): _A, ('JustTime', 'Corregir según matriz'): _E, ('JustTime', 'Aplicar sugerencia'): _E, ('JustTime', 'Limpiar datos'): _E,
    ('Correos', 'Sincronizar BBDD Correos'): _A, ('Correos', 'Registro'): _V, ('Correos', 'Botones de plantilla'): _C,
    ('Correos', 'Abrir en Outlook'): _C, ('Correos', 'Por vencer'): _V,
    ('Administración', 'Historial: Eliminar registros antiguos'): _E, ('Administración', 'Historial: Mostrar 10 días más'): _V, ('Administración', 'Instalaciones: Generar mes'): _A,
    ('Administración', 'Instalaciones: Renombrar / Eliminar hoja'): _E, ('Administración', 'Contactos: Agregar / Importar'): _E,
    ('Administración', 'Contactos: Corregir teléfonos'): _E, ('Administración', 'Contactos: Guardar cambios'): _E,
    ('Administración', 'Ejecutivos: Agregar / Editar / Desactivar'): _E, ('Administración', 'Excel / Recargar'): _X,
    ('Configuración', 'Examinar'): _E, ('Configuración', 'Autodetectar'): _E, ('Configuración', 'Abrir carpeta'): _V,
    ('Configuración', '¿Cómo me conecto?'): _V, ('Configuración', 'Actualizar copia de BBDD Clientes CM'): _A,
    ('Configuración', 'Guardar y reiniciar'): _E, ('Configuración', 'Editar (Enlaces)'): _E,
}

# Qué es cada pantalla, en una línea (tarjeta de la primera fase)
RESUMEN_PANTALLA = {
    'Comercial: barra superior': 'Los botones de arriba de Comercial: reportes, filtros, revisiones y guardado.',
    'Comercial: acciones rápidas': 'Lo que haces con una unidad o contrato: enviar, editar, renovar y marcar estados.',
    'Operaciones': 'Conectar, desconectar y ordenar la flota de las unidades que llegan de Comercial.',
    'Dashboard': 'Cómo le va a Volvo Connect: conectados, metas y dónde se pierden clientes.',
    'Clientes y Flota': 'La ficha del cliente y de cada unidad: historial, contratos anteriores y contactos.',
    'Provisiones': 'Provisiones por mes y plan: revisar, editar, guardar y copiar VIN.',
    'Contratos (CM)': 'Contratos de mantenimiento: filtrar, importar el Excel y corregir datos.',
    'Facturación Manual': 'Preparar la factura de cada empresa: precio en UF, PDF y etapa.',
    'JustTime': 'Estados y fechas de las unidades en JustTime.',
    'Correos': 'Enviar los avisos a los clientes con las plantillas y revisar lo ya enviado.',
    'Administración': 'Historial, instalaciones, contactos y ejecutivos.',
    'Configuración': 'Guardar las rutas y los enlaces de la aplicación.',
}


def _categoria(pantalla, boton):
    return CATEGORIA_BOTON.get((pantalla, boton), CATEGORIAS[0])


def _color_icono():
    return '#9CC2FF' if tema.es_oscuro() else _VOLVO


def _icono_boton(icono, tam=42, lado=20):
    """Casilla con el ícono que tiene el botón en la pantalla."""
    casilla = QLabel()
    casilla.setFixedSize(tam, tam)
    casilla.setAlignment(Qt.AlignmentFlag.AlignCenter)
    casilla.setPixmap(qta.icon(icono or 'fa5s.chart-bar', color=_color_icono()).pixmap(QSize(lado, lado)))
    casilla.setStyleSheet(f"background: {_VOLVO_SUAVE}; border-radius: 12px; border: none;")
    return casilla


class _Cuadricula(QWidget):
    """Reparte tarjetas en tantas columnas como quepan; los títulos ocupan todo el ancho."""

    def __init__(self, ancho_min, parent=None):
        super().__init__(parent)
        self._ancho_min = ancho_min
        self._items = []
        self._columnas = 0
        self._grilla = QGridLayout(self)
        self._grilla.setContentsMargins(0, 0, 0, 0)
        self._grilla.setSpacing(12)

    def minimumSizeHint(self):
        return QSize(self._ancho_min, 0)

    def agregar(self, widget, completo=False):
        self._items.append((widget, completo))
        widget.setParent(self)

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._acomodar()

    def showEvent(self, evento):
        super().showEvent(evento)
        self._acomodar(forzar=True)

    def _acomodar(self, forzar=False):
        columnas = max(1, (self.width() + 12) // (self._ancho_min + 12))
        if columnas == self._columnas and not forzar:
            return
        self._columnas = columnas
        while self._grilla.count():
            self._grilla.takeAt(0)
        for c in range(max(columnas, self._grilla.columnCount())):
            self._grilla.setColumnStretch(c, 1 if c < columnas else 0)
        fila = columna = 0
        for widget, completo in self._items:
            if completo:
                if columna:
                    fila, columna = fila + 1, 0
                self._grilla.addWidget(widget, fila, 0, 1, columnas)
                fila += 1
            else:
                self._grilla.addWidget(widget, fila, columna)
                columna += 1
                if columna == columnas:
                    fila, columna = fila + 1, 0
            widget.show()
        self.updateGeometry()


def _estilo_tarjeta(nombre):
    return (f"QFrame#{nombre} {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 14px; }}")


def _chip(texto, fondo=_VOLVO_SUAVE, color=_VOLVO):
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; border: none;")
    return lbl


def _tarjeta_boton(pantalla, boton, icono, hace, cuando, con_origen=False):
    """Tarjeta de un botón: encabezado azul con el nombre dibujado como el botón y, abajo, qué hace y cuándo usarlo."""
    marco = QFrame()
    marco.setObjectName("ayudaBoton")
    marco.setStyleSheet(_estilo_tarjeta("ayudaBoton"))
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    enc = QFrame()
    enc.setStyleSheet(f"background: {_VOLVO}; border: none; border-top-left-radius: 13px; border-top-right-radius: 13px;")
    fila_enc = QHBoxLayout(enc)
    fila_enc.setContentsMargins(12, 10, 12, 10)
    fila_enc.setSpacing(8)
    capsula = QFrame()
    capsula.setStyleSheet("background: rgba(255,255,255,0.16); border: none; border-radius: 10px;")
    fila_capsula = QHBoxLayout(capsula)
    fila_capsula.setContentsMargins(10, 6, 12, 6)
    fila_capsula.setSpacing(8)
    lbl_icono = QLabel()
    lbl_icono.setPixmap(qta.icon(icono or 'fa5s.chart-bar', color='white').pixmap(QSize(15, 15)))
    lbl_icono.setStyleSheet(_SIN_FONDO)
    lbl_boton = QLabel(boton)
    lbl_boton.setWordWrap(True)
    lbl_boton.setStyleSheet(f"font-size: 13px; font-weight: 700; color: white; {_SIN_FONDO}")
    fila_capsula.addWidget(lbl_icono, 0, Qt.AlignmentFlag.AlignVCenter)
    fila_capsula.addWidget(lbl_boton, 1)
    fila_enc.addWidget(capsula, 1)
    lay.addWidget(enc)

    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(14, 12, 14, 14)
    cuerpo.setSpacing(8)
    if con_origen:
        etiquetas = QHBoxLayout()
        etiquetas.setSpacing(6)
        etiquetas.addWidget(_chip(pantalla, _VOLVO, "white"))
        etiquetas.addWidget(_chip(_categoria(pantalla, boton)))
        etiquetas.addStretch()
        cuerpo.addLayout(etiquetas)
    lbl_hace = QLabel(hace)
    lbl_hace.setWordWrap(True)
    lbl_hace.setStyleSheet(f"font-size: 12px; color: {estilo_com.TINTA}; {_SIN_FONDO}")
    cuerpo.addWidget(lbl_hace)
    lbl_cuando = QLabel(f"<b>Cuándo usarlo:</b> {cuando}")
    lbl_cuando.setWordWrap(True)
    lbl_cuando.setStyleSheet(f"font-size: 11px; color: {estilo_com.APAGADO}; background: {estilo_com.SUPERFICIE_2}; "
                             "border: none; border-radius: 8px; padding: 6px 9px;")
    cuerpo.addWidget(lbl_cuando)
    cuerpo.addStretch()
    lay.addLayout(cuerpo, 1)
    return marco


class _TarjetaClic(QFrame):
    """Tarjeta que se puede pulsar (un QPushButton no se ajusta a lo que lleva dentro)."""
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        if evento.button() == Qt.MouseButton.LeftButton and self.rect().contains(evento.position().toPoint()):
            self.clicked.emit()


def _tarjeta_pantalla(titulo, icono, filas, al_abrir):
    """Tarjeta de la primera fase: la pantalla, cuántos botones tiene y de qué tipo."""
    boton = _TarjetaClic()
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setObjectName("ayudaPantalla")
    boton.setAttribute(Qt.WidgetAttribute.WA_Hover)
    boton.setStyleSheet(
        f"QFrame#ayudaPantalla {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 16px; }}"
        f"QFrame#ayudaPantalla:hover {{ border: 1px solid {_VOLVO}; }}")
    lay = QVBoxLayout(boton)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    cab = QHBoxLayout()
    cab.setSpacing(12)
    caja = QLabel()
    caja.setFixedSize(44, 44)
    caja.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caja.setPixmap(qta.icon(icono, color='white').pixmap(QSize(20, 20)))
    caja.setStyleSheet(f"background: {_VOLVO}; border-radius: 14px; border: none;")
    textos = QVBoxLayout()
    textos.setSpacing(2)
    lbl_titulo = QLabel(titulo)
    lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
    lbl_cuenta = QLabel(f"{len(filas)} botones")
    lbl_cuenta.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
    textos.addWidget(lbl_titulo)
    textos.addWidget(lbl_cuenta)
    flecha = QLabel()
    flecha.setPixmap(qta.icon('fa5s.arrow-right', color=estilo_com.APAGADO).pixmap(QSize(13, 13)))
    flecha.setStyleSheet(_SIN_FONDO)
    cab.addWidget(caja)
    cab.addLayout(textos, 1)
    cab.addWidget(flecha)
    lay.addLayout(cab)
    resumen = QLabel(RESUMEN_PANTALLA.get(titulo, ""))
    resumen.setWordWrap(True)
    resumen.setStyleSheet(f"font-size: 12px; color: {estilo_com.TINTA}; {_SIN_FONDO}")
    lay.addWidget(resumen)
    lay.addStretch(1)
    for hijo in boton.findChildren(QWidget):
        hijo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    boton.clicked.connect(al_abrir)
    return boton


def crear_pagina_ayuda(titulo_pagina=None):
    """Ayuda en dos fases: una tarjeta por pantalla y, al abrirla, sus botones agrupados por categoría.
    Una sola barra fija arriba (título o pantalla elegida, y el buscador) y, debajo, los filtros por categoría;
    solo se desplazan las tarjetas."""
    pagina = QWidget()
    pagina.setObjectName("paginaConfiguracion")
    pagina.setStyleSheet("QWidget#paginaConfiguracion { background: transparent; }")
    raiz = QVBoxLayout(pagina)
    raiz.setContentsMargins(0, 0, 0, 0)
    raiz.setSpacing(0)

    cabecera = QWidget()
    lay = QVBoxLayout(cabecera)
    lay.setContentsMargins(20, 18, 20, 12)
    lay.setSpacing(10)

    barra = QFrame()
    barra.setStyleSheet(f"background: {_VOLVO}; border: none; border-radius: 16px;")
    fila_barra = QHBoxLayout(barra)
    fila_barra.setContentsMargins(14, 12, 14, 12)
    fila_barra.setSpacing(12)
    atras = QPushButton(" Pantallas")
    atras.setIcon(qta.icon('fa5s.arrow-left', color='white'))
    atras.setCursor(Qt.CursorShape.PointingHandCursor)
    atras.setToolTip("Volver a todas las pantallas")
    atras.setStyleSheet(
        "QPushButton { background: rgba(255,255,255,0.14); color: white; border: none; border-radius: 10px; "
        "padding: 8px 14px; font-size: 12px; font-weight: 700; }"
        "QPushButton:hover { background: rgba(255,255,255,0.26); }")
    caja = QLabel()
    caja.setFixedSize(42, 42)
    caja.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caja.setStyleSheet("background: rgba(255,255,255,0.14); border-radius: 12px; border: none;")
    textos = QVBoxLayout()
    textos.setSpacing(2)
    lbl_titulo = QLabel()
    lbl_titulo.setStyleSheet(f"font-size: 17px; font-weight: 700; color: white; {_SIN_FONDO}")
    lbl_subtitulo = QLabel()
    lbl_subtitulo.setWordWrap(True)
    lbl_subtitulo.setStyleSheet(f"font-size: 12px; color: #C7D2E6; {_SIN_FONDO}")
    textos.addWidget(lbl_titulo)
    textos.addWidget(lbl_subtitulo)
    cuenta = QLabel()
    cuenta.setStyleSheet("background: rgba(255,255,255,0.14); color: white; border-radius: 12px; padding: 5px 12px; "
                         "font-size: 12px; font-weight: 700; border: none;")
    buscador = QLineEdit()
    buscador.setPlaceholderText("Buscar un botón o una acción…")
    buscador.setClearButtonEnabled(True)
    buscador.setMinimumWidth(260)
    buscador.setMaximumWidth(380)
    buscador.addAction(qta.icon('fa5s.search', color='#5B6980'), QLineEdit.ActionPosition.LeadingPosition)
    buscador.setStyleSheet(
        "QLineEdit { background: white; color: #0F1B33; border: 1px solid transparent; border-radius: 10px; "
        "padding: 9px 12px; font-size: 13px; }"
        "QLineEdit:focus { border: 1px solid #9CC2FF; }")
    fila_barra.addWidget(atras)
    fila_barra.addWidget(caja)
    fila_barra.addLayout(textos, 1)
    fila_barra.addWidget(cuenta)
    fila_barra.addWidget(buscador)
    lay.addWidget(barra)
    barra_chips = QHBoxLayout()
    barra_chips.setSpacing(8)
    lay.addLayout(barra_chips)
    raiz.addWidget(cabecera)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
    cuerpo = QWidget()
    cuerpo.setObjectName("cuerpoAyuda")
    cuerpo.setStyleSheet("QWidget#cuerpoAyuda { background: transparent; }")
    contenido = QVBoxLayout(cuerpo)
    contenido.setContentsMargins(20, 6, 20, 18)
    contenido.setSpacing(14)
    area.setWidget(cuerpo)
    raiz.addWidget(area, 1)
    estado = {'pantalla': None, 'categoria': None}

    def quitar(widget):
        widget.hide()
        widget.setParent(None)
        widget.deleteLater()

    def vaciar_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                quitar(item.widget())
            elif item.layout():
                vaciar_layout(item.layout())

    def vaciar():
        vaciar_layout(contenido)
        vaciar_layout(barra_chips)

    def poner_barra(titulo, subtitulo, icono, botones=None, con_atras=False):
        lbl_titulo.setText(titulo)
        lbl_subtitulo.setText(subtitulo)
        caja.setPixmap(qta.icon(icono, color='white').pixmap(QSize(20, 20)))
        atras.setVisible(con_atras)
        cuenta.setVisible(botones is not None)
        if botones is not None:
            cuenta.setText(f"{botones} botones")

    def vista_pantallas():
        vaciar()
        poner_barra("Ayuda de botones", "Qué hace cada botón y cuándo se usa. Elige una pantalla o busca.", 'fa5s.question-circle')
        cuadricula = _Cuadricula(320)
        for nombre, icono, filas in AYUDA:
            cuadricula.agregar(_tarjeta_pantalla(nombre, icono, filas, lambda _c=False, n=nombre: abrir(n)))
        contenido.addWidget(cuadricula)
        contenido.addStretch()

    def abrir(nombre):
        estado['pantalla'], estado['categoria'] = nombre, None
        vista_detalle()
        area.verticalScrollBar().setValue(0)

    def volver():
        estado['pantalla'] = None
        vista_pantallas()

    def elegir_categoria(categoria):
        estado['categoria'] = categoria
        vista_detalle()

    atras.clicked.connect(volver)

    def vista_detalle():
        vaciar()
        nombre, icono, filas = next(p for p in AYUDA if p[0] == estado['pantalla'])
        poner_barra(nombre, RESUMEN_PANTALLA.get(nombre, ""), icono, botones=len(filas), con_atras=True)
        presentes = [c for c in CATEGORIAS if any(_categoria(nombre, f[0]) == c for f in filas)]
        for categoria in [None] + presentes:
            n = len(filas) if categoria is None else sum(1 for f in filas if _categoria(nombre, f[0]) == categoria)
            activo = estado['categoria'] == categoria
            boton = QPushButton(f"{categoria or 'Todas'} · {n}")
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(
                f"QPushButton {{ background: {_VOLVO if activo else estilo_com.SUPERFICIE}; color: {'white' if activo else _VOLVO}; "
                f"border: 1px solid {_VOLVO if activo else estilo_com.LINEA}; border-radius: 12px; padding: 7px 14px; "
                "font-size: 12px; font-weight: 700; }"
                f"QPushButton:hover {{ border: 1px solid {_VOLVO}; }}")
            boton.clicked.connect(lambda _c=False, c=categoria: elegir_categoria(c))
            barra_chips.addWidget(boton)
        barra_chips.addStretch()

        cuadricula = _Cuadricula(360)
        mostrar_titulos = estado['categoria'] is None and len(presentes) > 1
        for categoria in presentes:
            if estado['categoria'] not in (None, categoria):
                continue
            tarjetas = [f for f in filas if _categoria(nombre, f[0]) == categoria]
            if mostrar_titulos:
                titulo = QWidget()
                fila_t = QHBoxLayout(titulo)
                fila_t.setContentsMargins(0, 6, 0, 0)
                fila_t.setSpacing(8)
                ic = QLabel()
                ic.setPixmap(qta.icon(_ICONO_CATEGORIA[categoria], color=_color_icono()).pixmap(QSize(15, 15)))
                lbl = QLabel(categoria)
                lbl.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
                linea = QFrame()
                linea.setFixedHeight(1)
                linea.setStyleSheet(f"background: {estilo_com.LINEA}; border: none;")
                fila_t.addWidget(ic)
                fila_t.addWidget(lbl)
                fila_t.addWidget(linea, 1)
                cuadricula.agregar(titulo, completo=True)
            for boton_, ico, hace, cuando in tarjetas:
                cuadricula.agregar(_tarjeta_boton(nombre, boton_, ico, hace, cuando))
        contenido.addWidget(cuadricula)
        contenido.addStretch()

    def vista_busqueda(texto):
        vaciar()
        resultados = [(p[0], f) for p in AYUDA for f in p[2]
                      if texto in f"{p[0]} {f[0]} {f[2]} {f[3]} {_categoria(p[0], f[0])}".lower()]
        poner_barra("Resultados de la búsqueda",
                    f"{len(resultados)} botones coinciden" if resultados else "No hay botones que coincidan con la búsqueda.",
                    'fa5s.search', con_atras=False)
        cuadricula = _Cuadricula(360)
        for pantalla, (boton_, ico, hace, cuando) in resultados:
            cuadricula.agregar(_tarjeta_boton(pantalla, boton_, ico, hace, cuando, con_origen=True))
        contenido.addWidget(cuadricula)
        contenido.addStretch()

    def al_buscar(texto):
        texto = texto.strip().lower()
        if texto:
            vista_busqueda(texto)
        elif estado['pantalla']:
            vista_detalle()
        else:
            vista_pantallas()

    def reconstruir(*_):
        al_buscar(buscador.text())

    buscador.textChanged.connect(al_buscar)
    tema.GestorTema.instancia().tema_cambiado.connect(lambda *_: None if sip.isdeleted(pagina) else reconstruir())
    vista_pantallas()
    pagina.buscador = buscador
    return pagina
