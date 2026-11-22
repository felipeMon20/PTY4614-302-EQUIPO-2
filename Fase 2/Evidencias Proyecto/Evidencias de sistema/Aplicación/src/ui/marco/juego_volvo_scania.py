"""Juego escondido del Modo Programador: Volvo contra Scania.

Jugabilidad de plataformas de arcade: vigas inclinadas, escaleras, neumáticos que ruedan (y a veces bajan por las
escaleras) y martillos. Todo se dibuja en una imagen de 224 x 256 píxeles que se amplía sin suavizado, para que se vea
como pantalla de arcade. Sin sonido ni imágenes: solo QPainter."""
import random

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

ANCHO, ALTO = 224, 256
DESNIVEL = 8
NEGRO = QColor("#000000")
VIGA_LUZ, VIGA, VIGA_SOMBRA = QColor("#FF9AA2"), QColor("#E0404A"), QColor("#8A1F2B")
ESCALERA = QColor("#27E0F0")
AMARILLO = QColor("#FFD800")
BLANCO = QColor("#FFFFFF")
ROJO = QColor("#FF3030")
PLATA = QColor("#C9D2DC")
AZUL_VOLVO = QColor("#2D6CDF")
AZUL_SCANIA = QColor("#0B2A5B")
GRIS = QColor("#8C96A6")

# (x inicial, x final, y del centro, sentido en que ruedan los neumáticos: +1 derecha, -1 izquierda, 0 plana)
VIGAS = [
    (0, 224, 246, -1),
    (0, 200, 214, +1),
    (24, 224, 182, -1),
    (0, 200, 150, +1),
    (24, 224, 118, -1),
    (0, 200, 86, +1),
    (96, 136, 52, 0),
]
# (x, viga de abajo): sube a la viga siguiente
ESCALERAS = [(88, 0), (180, 0), (160, 1), (64, 1), (56, 2), (170, 2), (168, 3), (72, 3), (56, 4), (180, 4), (112, 5)]
ESCALERAS_ROTAS = [(30, 0), (136, 2), (120, 4), (150, 1)]
MARTILLOS = [(3, 110), (1, 30)]
TAMBOR_X = 16
INICIO_X, INICIO_G = 24, 0
CLIENTE_X = 116

_FUENTE = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".####", "#....", "#....", "#..##", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "0": [".###.", "#..##", "#.#.#", "#.#.#", "#.#.#", "##..#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
    ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
    "!": ["..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."],
    ":": [".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
    "=": [".....", ".....", "#####", ".....", "#####", ".....", "....."],
}


def _glifo(c):
    return _FUENTE.get(c, ["....."] * 7)


def y_viga(g, x):
    x0, x1, yc, s = VIGAS[g]
    if s == 0:
        return yc
    t = (min(max(x, x0), x1) - x0) / (x1 - x0)
    return yc + s * DESNIVEL * (t - 0.5)


class TableroJuego(QWidget):
    """Pantalla del juego: título, partida, muerte, nivel superado y fin."""

    maximo = 0   # mejor puntaje de la sesión

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(ANCHO * 2, ALTO * 2)
        self._img = QImage(ANCHO, ALTO, QImage.Format.Format_RGB32)
        self._reloj = QTimer(self)
        self._reloj.setTimerType(Qt.TimerType.PreciseTimer)
        self._reloj.setInterval(16)
        self._reloj.timeout.connect(self._paso)
        self.teclas = set()
        self._saltar = False
        self.pausa = False
        self.estado = "titulo"
        self.t = 0
        self._nueva_partida()

    # ------------------------------------------------------------ partida
    def _nueva_partida(self):
        self.puntos = 0
        self.vidas = 3
        self.nivel = 1
        self._iniciar_nivel()

    def _iniciar_nivel(self):
        self.bonus = 5000
        self.barriles = []
        self.martillos = [{"g": g, "x": x} for g, x in MARTILLOS]
        self.destellos = []
        self.lanzando = 0
        self.proximo = 90
        self.velocidad = min(1.6, 0.9 + 0.12 * (self.nivel - 1))
        self.espera = max(60, 130 - 14 * (self.nivel - 1))
        self._poner_jugador()

    def _poner_jugador(self):
        self.p = {"x": float(INICIO_X), "y": y_viga(INICIO_G, INICIO_X), "g": INICIO_G, "estado": "suelo", "vy": 0.0,
                  "dir": 1, "anim": 0, "sdir": 0, "e": None, "martillo": 0}
        self.barriles = []

    def empezar(self):
        self._nueva_partida()
        self.estado = "juego"
        self.t = 0

    # ------------------------------------------------------------ vida del widget
    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()
        self._reloj.start()

    def hideEvent(self, e):
        self._reloj.stop()
        super().hideEvent(e)

    def focusOutEvent(self, e):
        self.teclas.clear()
        if self.estado == "juego":
            self.pausa = True
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or (k == Qt.Key.Key_Space and self.estado in ("titulo", "fin")):
            if self.estado in ("titulo", "fin"):
                self.empezar()
                return
        if k == Qt.Key.Key_P and self.estado == "juego":
            self.pausa = not self.pausa
            return
        if k == Qt.Key.Key_Space:
            self._saltar = True
        self.pausa = False if self.estado == "juego" and k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) else self.pausa
        self.teclas.add(k)

    def keyReleaseEvent(self, e):
        if not e.isAutoRepeat():
            self.teclas.discard(e.key())

    # ------------------------------------------------------------ lógica
    def _paso(self):
        self.t += 1
        if self.estado == "juego" and not self.pausa:
            self._actualizar()
        elif self.estado in ("muerte", "nivel"):
            self._espera -= 1
            if self._espera <= 0:
                self._despues_de_animacion()
        self.update()

    def _tecla(self, *ks):
        return any(k in self.teclas for k in ks)

    def _escalera_cerca(self, x, g, subir):
        for ex, gb in ESCALERAS:
            if abs(x - ex) <= 4 and ((subir and gb == g) or (not subir and gb + 1 == g)):
                return ex, gb
        return None

    def _actualizar(self):
        self._mover_jugador()
        self._mover_barriles()
        self._lanzar()
        self._choques()
        self.destellos = [d for d in self.destellos if d["t"] > 0]
        for d in self.destellos:
            d["t"] -= 1
        if self.t % 120 == 0:
            self.bonus -= 100
            if self.bonus <= 0:
                self._morir()
        if self.estado == "juego" and self.p["estado"] == "suelo" and self.p["g"] == 6 and abs(self.p["x"] - CLIENTE_X) < 10:
            self.puntos += self.bonus
            self.estado = "nivel"
            self._espera = 150

    def _mover_jugador(self):
        p = self.p
        izq, der = self._tecla(Qt.Key.Key_Left, Qt.Key.Key_A), self._tecla(Qt.Key.Key_Right, Qt.Key.Key_D)
        arriba, abajo = self._tecla(Qt.Key.Key_Up, Qt.Key.Key_W), self._tecla(Qt.Key.Key_Down, Qt.Key.Key_S)
        saltar, self._saltar = self._saltar, False
        martillo = p["martillo"] > 0
        if martillo:
            p["martillo"] -= 1
        vel = 0.8 if martillo else 1.0
        x0, x1 = VIGAS[p["g"]][0] + 4, VIGAS[p["g"]][1] - 4
        if p["estado"] == "suelo":
            dx = (1 if der else 0) - (1 if izq else 0)
            if dx:
                p["x"] = min(max(p["x"] + dx * vel, x0), x1)
                p["dir"] = dx
                p["anim"] += 1
            p["y"] = y_viga(p["g"], p["x"])
            if not martillo and (arriba or abajo):
                e = self._escalera_cerca(p["x"], p["g"], bool(arriba))
                if e:
                    p["estado"], p["e"], p["x"] = "escalera", e, float(e[0])
            if not martillo and saltar and p["estado"] == "suelo":
                p["estado"], p["vy"], p["sdir"] = "salto", -2.2, dx
        elif p["estado"] == "salto":
            p["vy"] += 0.12
            p["y"] += p["vy"]
            p["x"] = min(max(p["x"] + p["sdir"] * vel, x0), x1)
            suelo = y_viga(p["g"], p["x"])
            if p["vy"] > 0 and p["y"] >= suelo:
                p["y"], p["estado"] = suelo, "suelo"
        elif p["estado"] == "escalera":
            ex, gb = p["e"]
            p["y"] += ((1 if abajo else 0) - (1 if arriba else 0)) * 0.8
            if abs(p["y"]) and (arriba or abajo):
                p["anim"] += 1
            if p["y"] <= y_viga(gb + 1, ex):
                p["y"], p["g"], p["estado"] = y_viga(gb + 1, ex), gb + 1, "suelo"
            elif p["y"] >= y_viga(gb, ex):
                p["y"], p["g"], p["estado"] = y_viga(gb, ex), gb, "suelo"
        if not martillo and p["estado"] in ("suelo", "salto"):
            for m in self.martillos:
                if m["g"] == p["g"] and abs(p["x"] - m["x"]) < 7 and abs(p["y"] - y_viga(m["g"], m["x"])) < 8:
                    self.martillos.remove(m)
                    p["martillo"] = 600
                    break

    def _lanzar(self):
        self.proximo -= 1
        if self.lanzando > 0:
            self.lanzando -= 1
        if self.proximo <= 0:
            self.proximo = self.espera + random.randint(0, 40)
            self.lanzando = 24
        if self.lanzando == 1:
            self.barriles.append({"x": 46.0, "y": y_viga(5, 46), "g": 5, "e": "rueda", "dir": 1, "vy": 0.0, "vx": 0.0,
                                  "saltado": False, "usadas": set()})

    def _mover_barriles(self):
        for b in list(self.barriles):
            if b["e"] == "rueda":
                b["x"] += b["dir"] * self.velocidad
                b["y"] = y_viga(b["g"], b["x"])
                x0, x1, _y, s = VIGAS[b["g"]]
                if b["g"] == 0 and b["x"] <= TAMBOR_X + 6:
                    self.barriles.remove(b)
                    self.destellos.append({"x": TAMBOR_X, "y": y_viga(0, TAMBOR_X) - 14, "t": 10, "txt": ""})
                    continue
                if b["g"] > 0 and ((b["dir"] > 0 and b["x"] >= x1) or (b["dir"] < 0 and b["x"] <= x0)):
                    b["e"], b["vy"], b["vx"], b["g"] = "cae", 0.0, b["dir"] * 0.6, b["g"] - 1
                    continue
                for ex, gb in ESCALERAS:
                    if gb + 1 == b["g"] and abs(b["x"] - ex) < 1 and ex not in b["usadas"]:
                        b["usadas"].add(ex)
                        if random.random() < 0.3:
                            b["e"], b["x"] = "escalera", float(ex)
                            break
            elif b["e"] == "cae":
                b["vy"] += 0.12
                b["y"] += b["vy"]
                b["x"] += b["vx"]
                if b["y"] >= y_viga(b["g"], b["x"]) and b["vy"] > 0:
                    b["y"], b["e"] = y_viga(b["g"], b["x"]), "rueda"
                    b["dir"] = VIGAS[b["g"]][3] or 1
                    b["usadas"] = set()
            elif b["e"] == "escalera":
                b["y"] += 1.0
                if b["y"] >= y_viga(b["g"] - 1, b["x"]):
                    b["g"] -= 1
                    b["y"], b["e"] = y_viga(b["g"], b["x"]), "rueda"
                    b["dir"] = VIGAS[b["g"]][3] or 1
                    b["usadas"] = set()

    def _choques(self):
        p = self.p
        for b in list(self.barriles):
            if p["martillo"] > 0:
                hx = p["x"] + p["dir"] * 10
                if abs(b["x"] - hx) < 9 and abs((b["y"] - 5) - (p["y"] - 8)) < 10:
                    self.barriles.remove(b)
                    self.puntos += 300
                    self.destellos.append({"x": b["x"], "y": b["y"] - 12, "t": 30, "txt": "300"})
                    continue
            if p["estado"] == "salto" and not b["saltado"] and abs(b["x"] - p["x"]) < 5 and p["y"] < b["y"] - 9 and p["g"] == b["g"]:
                b["saltado"] = True
                self.puntos += 100
                self.destellos.append({"x": b["x"], "y": b["y"] - 18, "t": 30, "txt": "100"})
            if abs(b["x"] - p["x"]) < 8 and abs((b["y"] - 5) - (p["y"] - 7)) < 9:
                self._morir()
                return

    def _morir(self):
        if self.estado != "juego":
            return
        self.vidas -= 1
        self.estado = "muerte"
        self._espera = 100
        self.teclas.clear()

    def _despues_de_animacion(self):
        if self.estado == "nivel":
            self.nivel += 1
            self._iniciar_nivel()
            self.estado = "juego"
        elif self.vidas <= 0:
            TableroJuego.maximo = max(TableroJuego.maximo, self.puntos)
            self.estado = "fin"
        else:
            self._poner_jugador()
            self.proximo = 90
            self.estado = "juego"
        TableroJuego.maximo = max(TableroJuego.maximo, self.puntos)

    # ------------------------------------------------------------ dibujo
    def _texto(self, q, x, y, txt, color, escala=1):
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(color)
        for i, c in enumerate(str(txt).upper()):
            for fy, fila in enumerate(_glifo(c)):
                for fx, v in enumerate(fila):
                    if v == "#":
                        q.drawRect(int(x + (i * 6 + fx) * escala), int(y + fy * escala), escala, escala)

    def _ancho_texto(self, txt, escala=1):
        return (len(str(txt)) * 6 - 1) * escala

    def _centrado(self, q, y, txt, color, escala=1):
        self._texto(q, (ANCHO - self._ancho_texto(txt, escala)) // 2, y, txt, color, escala)

    def _rect(self, q, x, y, w, h, color):
        q.fillRect(int(x), int(y), int(w), int(h), color)

    def _disco(self, q, cx, cy, r, color):
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(color)
        q.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))

    def _volvo(self, q, cx, pies, anim, escalera=False):
        cy = pies - 9
        self._disco(q, cx, cy, 6, PLATA)
        self._disco(q, cx, cy, 4, QColor("#101828"))
        self._rect(q, cx - 6, cy - 1, 12, 3, AZUL_VOLVO)
        self._rect(q, cx + 3, cy - 8, 4, 1, PLATA)
        self._rect(q, cx + 6, cy - 8, 1, 4, PLATA)
        paso = (anim // 4) % 2
        if escalera:
            self._rect(q, cx - 4, pies - 3 + paso, 2, 3 - paso, AZUL_VOLVO)
            self._rect(q, cx + 2, pies - 3 + (1 - paso), 2, 3 - (1 - paso), AZUL_VOLVO)
        else:
            self._rect(q, cx - 4 - paso, pies - 3, 3, 3, AZUL_VOLVO)
            self._rect(q, cx + 1 + paso, pies - 3, 3, 3, AZUL_VOLVO)

    def _martillo(self, q, x, y, arriba, d):
        if arriba:
            self._rect(q, x + d * 3 - 1, y - 20, 2, 8, QColor("#B5651D"))
            self._rect(q, x + d * 3 - 4, y - 24, 8, 4, GRIS)
        else:
            self._rect(q, x + d * 6, y - 9, 8, 2, QColor("#B5651D"))
            self._rect(q, x + d * 12 - (3 if d > 0 else 0), y - 13, 3, 8, GRIS)

    def _scania(self, q, x, pies, brazos):
        """Villano: insignia de Scania con cara de enojado que lanza neumáticos."""
        self._disco(q, x, pies - 21, 11, AZUL_SCANIA)
        self._disco(q, x, pies - 21, 9, QColor("#1B4A8C"))
        self._rect(q, x - 5, pies - 25, 3, 3, BLANCO)
        self._rect(q, x + 3, pies - 25, 3, 3, BLANCO)
        self._rect(q, x - 4, pies - 24, 1, 2, ROJO)
        self._rect(q, x + 4, pies - 24, 1, 2, ROJO)
        self._rect(q, x - 6, pies - 29, 5, 1, ROJO)
        self._rect(q, x + 2, pies - 29, 5, 1, ROJO)
        self._rect(q, x - 18, pies - 10, 37, 10, AZUL_SCANIA)
        self._rect(q, x - 18, pies - 10, 37, 1, BLANCO)
        self._texto(q, x - 17, pies - 8, "SCANIA", BLANCO)
        self._rect(q, x - 20, pies - (24 if brazos else 14), 3, 9, AZUL_SCANIA)
        self._rect(q, x + 18, pies - (24 if brazos else 14), 3, 9, AZUL_SCANIA)

    def _neumatico(self, q, b):
        cx, cy = int(b["x"]), int(b["y"] - 5)
        self._disco(q, cx, cy, 5, QColor("#202020"))
        self._disco(q, cx, cy, 2, PLATA)
        giro = int(b["x"] / 3) % 4
        dx, dy = ((0, -3), (3, 0), (0, 3), (-3, 0))[giro]
        self._rect(q, cx + dx, cy + dy, 1, 1, BLANCO)

    def _cliente(self, q, x, pies):
        """El cliente que hay que rescatar: persona con casco y camisa azul que pide ayuda con los brazos arriba."""
        brazos = (self.t // 12) % 2
        piel, camisa = QColor("#F2C9A0"), AZUL_VOLVO
        self._rect(q, x - 3, pies - 5, 3, 5, QColor("#2B2B3A"))
        self._rect(q, x + 1, pies - 5, 3, 5, QColor("#2B2B3A"))
        self._rect(q, x - 4, pies - 12, 9, 7, camisa)
        self._rect(q, x - 1, pies - 12, 3, 2, BLANCO)
        self._rect(q, x - 6, pies - (18 if brazos else 11), 2, 7, piel)
        self._rect(q, x + 5, pies - (18 if brazos else 11), 2, 7, piel)
        self._rect(q, x - 3, pies - 18, 7, 6, piel)
        self._rect(q, x - 1, pies - 16, 1, 1, NEGRO)
        self._rect(q, x + 2, pies - 16, 1, 1, NEGRO)
        self._rect(q, x - 4, pies - 20, 9, 3, AMARILLO)
        self._rect(q, x - 5, pies - 18, 11, 1, AMARILLO)
        self._texto(q, x - 15, pies - 30, "CLIENTE" if (self.t // 40) % 2 else "AYUDA!", ROJO)

    def _escenario(self, q):
        for g, (x0, x1, _yc, s) in enumerate(VIGAS):
            for x in range(x0, x1):
                y = int(round(y_viga(g, x)))
                self._rect(q, x, y, 1, 1, VIGA_LUZ)
                self._rect(q, x, y + 1, 1, 4, VIGA)
                self._rect(q, x, y + 5, 1, 1, VIGA_SOMBRA)
                if x % 8 == 3:
                    self._rect(q, x, y + 2, 2, 2, NEGRO)
        for ex, gb in ESCALERAS:
            self._escalera(q, ex, y_viga(gb + 1, ex), y_viga(gb, ex), 0)
        for ex, gb in ESCALERAS_ROTAS:
            top, bot = y_viga(gb + 1, ex), y_viga(gb, ex)
            self._escalera(q, ex, top + 10, bot, 0)
        # tambor de aceite con fuego
        ty = y_viga(0, TAMBOR_X)
        self._rect(q, TAMBOR_X - 10, ty - 16, 20, 16, QColor("#1B4F9C"))
        self._rect(q, TAMBOR_X - 10, ty - 11, 20, 1, PLATA)
        self._texto(q, TAMBOR_X - 8, ty - 9, "OIL", BLANCO)
        llama = 3 + (self.t // 6) % 3
        self._rect(q, TAMBOR_X - 3, ty - 16 - llama, 6, llama, QColor("#FF8A00"))
        self._rect(q, TAMBOR_X - 1, ty - 16 - llama - 1, 2, 2, QColor("#FFE000"))

    def _escalera(self, q, ex, y_alto, y_bajo, _extra):
        self._rect(q, ex - 3, y_alto, 1, y_bajo - y_alto, ESCALERA)
        self._rect(q, ex + 3, y_alto, 1, y_bajo - y_alto, ESCALERA)
        y = int(y_alto) + 2
        while y < y_bajo - 1:
            self._rect(q, ex - 3, y, 7, 1, ESCALERA)
            y += 4

    def _hud(self, q):
        self._texto(q, 16, 4, "1UP", ROJO)
        self._texto(q, 16, 13, f"{self.puntos:06d}", BLANCO)
        self._centrado(q, 4, "HIGH SCORE", ROJO)
        self._centrado(q, 13, f"{max(self.puntos, TableroJuego.maximo):06d}", BLANCO)
        self._texto(q, 170, 4, "BONUS", ROJO)
        self._texto(q, 170, 13, f"{max(0, self.bonus):04d}", AMARILLO)
        self._texto(q, 170, 24, f"L={self.nivel:02d}", AZUL_VOLVO.lighter(150))
        for i in range(max(0, self.vidas)):
            self._disco(q, 20 + i * 14, 30, 5, PLATA)
            self._rect(q, 15 + i * 14, 29, 10, 2, AZUL_VOLVO)

    def _pintar_juego(self, q):
        self._hud(q)
        self._escenario(q)
        for m in self.martillos:
            self._martillo(q, m["x"], y_viga(m["g"], m["x"]), (self.t // 10) % 2 == 0, 1)
        self._cliente(q, CLIENTE_X, y_viga(6, CLIENTE_X))
        self._scania(q, 28, y_viga(5, 28), self.lanzando > 0)
        for b in self.barriles:
            self._neumatico(q, b)
        p = self.p
        if self.estado == "muerte":
            giro = self._espera // 6 % 2
            self._volvo(q, p["x"] + (3 if giro else -3), p["y"] + (0 if giro else -2), 0)
            self._centrado(q, 120, "OUCH!", ROJO, 2)
        else:
            self._volvo(q, int(p["x"]), int(p["y"]), p["anim"], p["estado"] == "escalera")
            if p["martillo"] > 0:
                self._martillo(q, int(p["x"]), int(p["y"]), (self.t // 8) % 2 == 0, p["dir"])
        for d in self.destellos:
            if d["txt"]:
                self._texto(q, int(d["x"]) - 8, int(d["y"]), d["txt"], BLANCO)
        if self.estado == "nivel":
            self._centrado(q, 110, "STAGE CLEAR", AMARILLO, 2)
            self._centrado(q, 134, f"BONUS {self.bonus}", BLANCO)
        if self.pausa:
            self._centrado(q, 120, "PAUSA", AMARILLO, 2)

    def _pintar_titulo(self, q, fin=False):
        self._centrado(q, 24, "1UP", ROJO)
        self._centrado(q, 34, f"{self.puntos:06d}" if fin else "000000", BLANCO)
        self._centrado(q, 52, "HIGH SCORE", ROJO)
        self._centrado(q, 62, f"{TableroJuego.maximo:06d}", BLANCO)
        self._centrado(q, 84, "VOLVO", AZUL_VOLVO.lighter(160), 3)
        self._centrado(q, 112, "VS", BLANCO, 2)
        self._scania(q, ANCHO // 2, 160, (self.t // 15) % 2 == 0)
        self._volvo(q, ANCHO // 2 - 60, 160, self.t)
        self._cliente(q, ANCHO // 2 + 62, 160)
        if fin:
            self._centrado(q, 168, "GAME OVER", ROJO, 2)
        if (self.t // 30) % 2 == 0:
            self._centrado(q, 188, "PRESS START", AMARILLO, 2)
        self._centrado(q, 214, "FLECHAS: MOVER Y ESCALERAS", GRIS)
        self._centrado(q, 224, "ESPACIO: SALTAR   P: PAUSA", GRIS)
        self._centrado(q, 238, "ENTER = START", BLANCO)

    def _dibujar(self):
        self._img.fill(NEGRO)
        q = QPainter(self._img)
        if self.estado in ("titulo", "fin"):
            self._pintar_titulo(q, self.estado == "fin")
        else:
            self._pintar_juego(q)
        q.end()

    def paintEvent(self, event):
        self._dibujar()
        p = QPainter(self)
        p.fillRect(self.rect(), NEGRO)
        escala = min(self.width() / ANCHO, self.height() / ALTO)
        w, h = ANCHO * escala, ALTO * escala
        p.drawImage(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), self._img)
        p.end()


class JuegoDialogo(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Volvo vs Scania")
        self.setStyleSheet("QDialog { background: #000000; }")
        self.resize(ANCHO * 2 + 40, ALTO * 2 + 40)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tablero = TableroJuego(self)
        lay.addWidget(self.tablero)
