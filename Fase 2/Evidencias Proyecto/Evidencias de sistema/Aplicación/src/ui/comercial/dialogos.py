"""Diálogo de acciones sobre contratos CM de Comercial."""
from src.theme.colors import DANGER, PRIMARY, SUCCESS, WARNING
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.core.constants import VALOR_ESTADO_COMERCIAL_BAJA


# =========================================================
# DIÁLOGO MODERNO REUTILIZABLE (Confirmar baja de CM)
# =========================================================
class DialogoAccionCm(DialogoAccion):
    """Estados del flujo "Confirmar baja" y demás acciones de Gestionar CM
    sobre la tarjeta compartida DialogoAccion (ver src/ui/dialogo_accion.py)."""

    @classmethod
    def confirmacion(cls, parent, vins):
        """Diálogo previo a confirmar: reemplaza el QMessageBox.question de
        antes. `vins` es la lista (ya deduplicada) de VIN seleccionados en
        Gestionar CM. Acento rojo/danger en el botón principal: es una
        acción de negocio importante (da de baja el contrato y lo envía a Operaciones)."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Confirmar baja de CM",
            icon_name="fa5s.file-signature", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo="Confirmar baja de CM",
            subtitulo=f"{cantidad} {plural} seleccionado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "El contrato pasará a Baja y el estado de CM a Terminated. Operaciones recibirá "
                "los vehículos seleccionados en Bajas para desconectarlos. Los datos del CM se conservan."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Confirmar baja', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def vins_faltantes_en_correos(cls, parent, vins):
        """Aviso cuando uno o mas VIN seleccionados en Gestionar CM no
        estan en Correos.csv (desactualizado respecto a Comercial, ver
        mail_sync_service.cruzar_correos_maestro): no abre MailDialog
        preseleccionado; ofrece abrir el Gestor de Correos normal para que
        el usuario sincronice manualmente (nunca se dispara sola). Boton
        principal en rol 'accept' == "voy a abrir el Gestor de Correos"."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " VIN sin registro en Correos",
            icon_name="fa5s.exclamation-triangle", icon_color=WARNING, icon_bg_color="#FEF3C7",
            titulo="Faltan VIN en Correos.csv",
            subtitulo=f"{cantidad} {plural} sin registro",
            descripcion=(
                "Estos VIN no están en Correos.csv todavía (la base de correos está "
                "desactualizada respecto a Comercial). Sincroniza primero desde el "
                "Gestor de Correos (Sincronizar BBDD Correos) y vuelve a intentar Enviar Correo."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Abrir Gestor de Correos', 'clase': 'primary', 'rol': 'accept'},
            ],
        )

    @classmethod
    def confirmacion_enviar_operaciones(cls, parent, vins, estado_destino=VALOR_ESTADO_COMERCIAL_BAJA):
        """Diálogo previo a "Enviar a operaciones" (22-09-2026): el cliente
        rechazó la renovación (o cualquier otro motivo de baja detectado en
        Comercial) y la unidad debe pasar a gestión de Operaciones. Mismo
        patrón visual que confirmacion() (baja de CM), acento danger porque
        también es una acción de negocio importante.

        `estado_destino` (23-09-2026): BAJA en todas las sub-pestañas salvo
        "Vigentes", que envía BAJA SOLICITADA (ciclo de baja anticipada, ver
        _on_accion_enviar_operaciones_clicked) -- el texto refleja el estado
        real que va a quedar, no siempre "Baja"."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Enviar a operaciones",
            icon_name="fa5s.bolt", icon_color=DANGER, icon_bg_color="#FEE2E2",
            titulo="Enviar a operaciones",
            subtitulo=f"{cantidad} {plural} seleccionado{'s' if cantidad != 1 else ''}",
            descripcion=(
                f"Se cambiará ESTADO COMERCIAL a \"{estado_destino.title()}\" en los vehículos "
                "seleccionados. Dejarán de aparecer en Renovaciones y quedarán a la espera de que "
                "Operaciones confirme la desconexión."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Enviar a operaciones', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_enviar_operaciones(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Enviar a operaciones" (ver confirmacion_enviar_operaciones)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Enviado a operaciones",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Enviado a operaciones",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Baja\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def confirmacion_marcar_vencidos(cls, parent, vins):
        """Diálogo previo a "Marcar como Vencido" (sub-pestaña Vencidos,
        23-09-2026): a diferencia de confirmacion_enviar_operaciones, `vins`
        no viene de la selección de la tabla, sino de TODOS los vehículos
        de la bandeja "Vencidos" cuyo ESTADO COMERCIAL todavía no dice
        "Vencido" (ver ComercialModule._on_accion_marcar_vencido_clicked).
        Mismo patrón visual que confirmacion_enviar_operaciones."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Marcar como Vencido",
            icon_name="fa5s.calendar-times", icon_color=DANGER, icon_bg_color="#FEE2E2",
            titulo="Marcar como Vencido",
            subtitulo=f"{cantidad} {plural} desactualizado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "Se cambiará ESTADO COMERCIAL a \"Vencido\" en los vehículos de esta lista "
                "cuyo TÉRMINO CONTRATO ya pasó pero siguen en \"Vigente\" o \"Activación "
                "Pendiente\" (posible error humano al no actualizar el estado). No se "
                "modifican los que ya están en Baja, Baja Solicitada o Revisar: esos estados "
                "reflejan una decisión de negocio ya tomada."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Marcar como Vencido', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_marcar_vencidos(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Marcar como Vencido" (ver confirmacion_marcar_vencidos)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Vencidos actualizados",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Vencidos actualizados",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Vencido\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def confirmacion_marcar_vigentes(cls, parent, vins):
        """Diálogo previo a "Marcar como Vigente" (sub-pestaña Vigentes,
        24-09-2026, pedido explícito del usuario): `vins` viene de TODOS los
        vehículos de la bandeja "Vigentes" con ESTADO COMERCIAL =
        "Activación Pendiente" Y ESTADO DE ACTIVACIÓN ACTUAL = "Conectado"
        (ver ComercialModule._on_accion_marcar_vigente_clicked) -- unidades
        que Volvo Connect ya muestra conectadas pero cuyo ESTADO COMERCIAL
        quedó desactualizado (error humano). Mismo patrón visual que
        confirmacion_marcar_vencidos."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Marcar como Vigente",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Marcar como Vigente",
            subtitulo=f"{cantidad} {plural} desactualizado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "Se cambiará ESTADO COMERCIAL a \"Vigente\" en los vehículos de esta lista "
                "que ya figuran \"Conectado\" pero siguen en \"Activación Pendiente\" "
                "(posible error humano al no actualizar el estado)."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Marcar como Vigente', 'clase': 'primary', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_marcar_vigentes(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Marcar como Vigente" (ver confirmacion_marcar_vigentes)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Vigentes actualizados",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Vigentes actualizados",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Vigente\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def exito(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Baja confirmada",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Baja confirmada",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="La baja del CM se confirmó y guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )
