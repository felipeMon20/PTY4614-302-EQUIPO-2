"""Muestra los QMessageBox de toda la app con la tarjeta moderna DialogoAccion.

instalar() reemplaza QMessageBox.exec y las funciones estáticas
(information/warning/critical/question) en la app real, igual que tema.py
envuelve QWidget.setStyleSheet. Los módulos siguen llamando a QMessageBox
como siempre, así los tests (que parchean QMessageBox) no cambian. Solo se
llama desde main.py; en los tests QMessageBox queda nativo."""
import os
import re
import subprocess

from PyQt6.QtWidgets import QMessageBox

from src.ui.dialogo_accion import DialogoAccion
from src.theme.colors import PRIMARY, SUCCESS, WARNING, DANGER

SB = QMessageBox.StandardButton
Rol = QMessageBox.ButtonRole

_TEXTOS_BOTON = {
    SB.Ok: "Aceptar", SB.Yes: "Sí", SB.No: "No", SB.Cancel: "Cancelar",
    SB.Save: "Guardar", SB.Discard: "Descartar", SB.Close: "Cerrar",
    SB.Retry: "Reintentar", SB.Abort: "Abortar", SB.Ignore: "Ignorar",
    SB.Apply: "Aplicar", SB.Open: "Abrir", SB.YesToAll: "Sí a todo",
    SB.NoToAll: "No a todo", SB.Reset: "Restablecer", SB.SaveAll: "Guardar todo",
    SB.RestoreDefaults: "Restaurar", SB.Help: "Ayuda",
}
# Un "information" con estas palabras en el título se muestra como éxito
_PALABRAS_EXITO = ("éxito", "exito", "guardad", "actualizad", "exportad", "eliminad",
                   "agregad", "listo", "completad", "enviado", "renombrad", "restaurad")

_ESTILOS = {
    'info': ("fa5s.info-circle", PRIMARY, "#EFF6FF"),
    'exito': ("fa5s.check-circle", SUCCESS, "#D1FAE5"),
    'aviso': ("fa5s.exclamation-triangle", WARNING, "#FEF3C7"),
    'error': ("fa5s.times-circle", DANGER, "#FEE2E2"),
    'pregunta': ("fa5s.question-circle", PRIMARY, "#EFF6FF"),
}

_exec_nativo = QMessageBox.exec


def _tipo(msg):
    icono = msg.icon()
    if icono == QMessageBox.Icon.Critical:
        return 'error'
    if icono == QMessageBox.Icon.Warning:
        return 'aviso'
    if icono == QMessageBox.Icon.Question:
        return 'pregunta'
    titulo = msg.windowTitle().lower()
    if any(p in titulo for p in _PALABRAS_EXITO):
        return 'exito'
    return 'info'


def _clase(rol):
    if rol == Rol.DestructiveRole:
        return 'danger'
    if rol in (Rol.AcceptRole, Rol.YesRole, Rol.ApplyRole):
        return 'primary'
    return 'secondary'


def _orden(rol):
    if rol in (Rol.RejectRole, Rol.NoRole):
        return 0
    if rol in (Rol.AcceptRole, Rol.YesRole, Rol.ApplyRole):
        return 2
    return 1


def ruta_en_texto(texto):
    """Primera ruta de archivo o carpeta existente mencionada en el texto."""
    for linea in str(texto).splitlines():
        linea = linea.strip().strip('"\'')
        if len(linea) > 3 and os.path.exists(linea):
            return linea
    for candidato in re.findall(r'[A-Za-z]:\\[^\n"<>|*?]+', str(texto)):
        candidato = candidato.strip().rstrip('.,;:)')
        if os.path.exists(candidato):
            return candidato
    return None


def abrir_carpeta(ruta):
    ruta = os.path.normpath(ruta)
    try:
        if os.path.isfile(ruta):
            subprocess.Popen(['explorer', '/select,', ruta])
        else:
            os.startfile(ruta)
    except Exception as e:
        print(f"No se pudo abrir la carpeta {ruta}: {e}")


def _partible(texto):
    # Permite cortar rutas largas sin espacios en la tarjeta
    return re.sub(r'([\\/])', '\\1\u200b', texto) if ('\\' in texto or '/' in texto) and '<' not in texto else texto


def _boton_escape(msg, botones):
    for b in botones:
        if msg.buttonRole(b) in (Rol.RejectRole, Rol.NoRole):
            return b
    if len(botones) == 1:
        return botones[0]
    for sb in (SB.Cancel, SB.No, SB.Close):
        b = msg.button(sb)
        if b is not None:
            return b
    return None


def _exec_tarjeta(self):
    # El texto de detalle (error fatal de arranque) solo existe en la ventana nativa
    if self.detailedText():
        return _exec_nativo(self)
    botones = self.buttons()
    if not botones:
        self.setStandardButtons(SB.Ok)
        botones = self.buttons()

    tipo = _tipo(self)
    icono, color, fondo = _ESTILOS[tipo]
    titulo = self.windowTitle().strip() or "Aviso"
    descripcion = self.text()
    if self.informativeText():
        descripcion = f"{descripcion}\n\n{self.informativeText()}" if descripcion else self.informativeText()

    elegido = {}
    tarjeta = None

    def elegir(b):
        elegido['btn'] = b
        tarjeta.accept()

    specs = []
    ruta = ruta_en_texto(descripcion)
    if ruta:
        specs.append({'texto': "Abrir carpeta", 'clase': 'secondary', 'icono': 'fa5s.folder-open',
                      'accion': lambda _=False, r=ruta: abrir_carpeta(r)})
    por_defecto = self.defaultButton()
    for b in sorted(botones, key=lambda b: _orden(self.buttonRole(b))):
        rol = self.buttonRole(b)
        texto = _TEXTOS_BOTON.get(self.standardButton(b)) or b.text().replace('&', '')
        specs.append({
            'texto': texto, 'clase': _clase(rol),
            'accion': lambda _=False, b=b: elegir(b),
            'default': b is por_defecto or (por_defecto is None and _orden(rol) == 2),
        })

    tarjeta = DialogoAccion(self.parentWidget(), f" {titulo}", icon_name=icono, icon_color=color,
                            icon_bg_color=fondo, titulo=titulo, subtitulo=None,
                            descripcion=_partible(descripcion), botones=specs)
    tarjeta.exec()

    b = elegido.get('btn') or _boton_escape(self, botones)
    if b is None:
        return 0
    # Registra la elección en el QMessageBox para que clickedButton() funcione
    b.click()
    sb = self.standardButton(b)
    return sb if sb != SB.NoButton else self.result()


def _crear_estatica(icono, botones_por_defecto):
    def estatica(parent, title, text, buttons=botones_por_defecto, defaultButton=SB.NoButton):
        msg = QMessageBox(icono, title, text, buttons, parent)
        if defaultButton != SB.NoButton:
            msg.setDefaultButton(defaultButton)
        return msg.exec()
    return staticmethod(estatica)


def instalar():
    if QMessageBox.exec is _exec_tarjeta:
        return
    QMessageBox.exec = _exec_tarjeta
    QMessageBox.information = _crear_estatica(QMessageBox.Icon.Information, SB.Ok)
    QMessageBox.warning = _crear_estatica(QMessageBox.Icon.Warning, SB.Ok)
    QMessageBox.critical = _crear_estatica(QMessageBox.Icon.Critical, SB.Ok)
    QMessageBox.question = _crear_estatica(QMessageBox.Icon.Question, SB.Yes | SB.No)
