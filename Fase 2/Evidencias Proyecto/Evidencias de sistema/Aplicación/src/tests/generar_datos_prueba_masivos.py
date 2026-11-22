"""Amplía una carpeta de datos de prueba hasta ~12.000 unidades con datos 100% inventados.
Conserva lo que ya existe y agrega empresas, contratos, contactos y provisiones.
Uso: python generar_datos_prueba_masivos.py <carpeta> [total_unidades]"""
import calendar
import math
import os
import random
import sys
import unicodedata
from datetime import date, timedelta

import pandas as pd

HOY = date(2026, 11, 13)
SEMILLA = 20261113
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]

PREFIJOS = {
    "TRANSPORTES": ["Larga Distancia", "Carga Mixta", "Bienes de Consumo Diario"],
    "LOGÍSTICA": ["Distribución", "Bienes de Consumo Diario", "Carga Mixta"],
    "MINERA": ["Minería"],
    "CONSTRUCTORA": ["Construcción"],
    "AGRÍCOLA": ["Agricultura"],
    "FORESTAL": ["Forestal"],
    "SERVICIOS": ["Servicio", "Servicio Público", "Industrial"],
    "DISTRIBUIDORA": ["Distribución", "Bienes de Consumo Diario"],
    "COMBUSTIBLES": ["Combustibles"],
    "ÁRIDOS": ["Construcción", "Minería"],
    "RECICLAJES": ["Residuos y Reciclaje"],
    "INDUSTRIAL": ["Industrial"],
    "FRIGORÍFICOS": ["Bienes de Consumo Diario", "Agricultura"],
    "CARGAS": ["Carga Mixta", "Larga Distancia"],
    "SANEAMIENTO": ["Residuos y Reciclaje", "Servicio Público"],
    "AGROINDUSTRIAL": ["Agricultura", "Industrial"],
}
LUGARES = [
    "Arica", "Iquique", "Calama", "Antofagasta", "Copiapó", "Atacama", "Elqui", "Limarí", "Coquimbo",
    "Aconcagua", "Valparaíso", "Casablanca", "Quillota", "Maipo", "Cordillera", "Melipilla", "Rancagua",
    "Cachapoal", "Colchagua", "Curicó", "Talca", "Maule", "Linares", "Ñuble", "Chillán", "Concepción",
    "Biobío", "Arauco", "Los Ángeles", "Araucanía", "Temuco", "Valdivia", "Osorno", "Llanquihue",
    "Puerto Montt", "Chiloé", "Aysén", "Coyhaique", "Magallanes", "Punta Arenas", "Andes", "Pacífico",
    "Austral", "Central", "Norte Grande", "Del Sur", "Los Lagos", "Los Ríos", "Alerce", "Roble", "Huemul",
    "Pehuén", "Coihue", "Cóndor", "Lican Ray", "Pudahuel", "Quilicura", "Maipú", "San Antonio", "Cabildo",
    "Ovalle", "Vallenar", "Tocopilla", "Mejillones", "Cañete", "Lota", "Penco", "Lautaro", "Villarrica",
    "Pucón", "Futrono", "Paillaco", "Frutillar", "Calbuco", "Ancud", "Castro", "Cochrane", "Natales",
]
SUFIJOS = ["LTDA", "SPA", "S.A."]
COMUNAS = [
    ("Santiago", "Metropolitana"), ("Pudahuel", "Metropolitana"), ("Quilicura", "Metropolitana"),
    ("Maipú", "Metropolitana"), ("Talca", "Maule"), ("Curicó", "Maule"), ("Rancagua", "O'Higgins"),
    ("Antofagasta", "Antofagasta"), ("Calama", "Antofagasta"), ("La Serena", "Coquimbo"),
    ("Temuco", "Araucanía"), ("Puerto Montt", "Los Lagos"), ("Osorno", "Los Lagos"),
    ("Concepción", "Biobío"), ("Chillán", "Ñuble"), ("Valparaíso", "Valparaíso"),
    ("Iquique", "Tarapacá"), ("Copiapó", "Atacama"), ("Punta Arenas", "Magallanes"),
]
EJECUTIVOS = [("Ignacio Tapia", 28), ("Daniela Pizarro", 21), ("Sebastián Lagos", 15), ("Matías Soto", 10),
              ("Camila Rojas", 10), ("Rodrigo Bustos", 7), ("Fernanda Carrasco", 5), ("Valentina Fuentes", 4)]
NOMBRES = ["Andrés", "Gloria", "Paola", "Luis", "Marcela", "Cristián", "Javiera", "Pedro", "Carolina", "Jorge",
           "Patricio", "Verónica", "Héctor", "Claudia", "Mauricio", "Lorena", "Felipe", "Constanza", "Álvaro", "Susana"]
APELLIDOS = ["Rojas", "Silva", "Morales", "Rodríguez", "Muñoz", "Soto", "Contreras", "Fuentes", "Díaz", "Pérez",
             "González", "Araya", "Vega", "Tapia", "Reyes", "Núñez", "Carrasco", "Cortés", "Herrera", "Vargas"]
MODELOS = [("FE", 17), ("FME", 16), ("FH", 16), ("FHE", 14), ("FMX", 13), ("FM", 13), ("FL", 11)]
WMI = [("YV2", 36), ("93K", 34), ("9BV", 30)]
SERVICIOS = [("Basico", 21), ("Medio", 20), ("Full", 17), ("Medio + CIV", 22), ("Full + CIV", 20)]
PRECIOS_PLAN = {"Basico": 19000, "Medio": 38000, "Full": 57000, "Full + CIV": 76000, "Medio + CIV": 57000}
FORMAS = [("Venta", 27), ("Conversion", 16), ("Provision", 15), ("CMG", 11), ("CMB", 8), ("CMS", 7),
          ("Revisar", 6), ("Provision +", 6), ("Sin Contrato", 4)]
TIPO_CM = {"CMB": "Blue", "CMG": "Gold", "CMS": "Silver"}
PAGO_CM = {"Blue": [89900, 119900], "Silver": [119900, 149900], "Gold": [189900, 239900]}
ESTADOS = [("Vigente", 58), ("Baja", 13), ("Activación Pendiente", 14), ("Vencido", 11),
           ("Baja Solicitada", 2), ("Renovado", 2)]
OBS = ["Cliente solicita revisar plan", "Pendiente confirmar contacto", "Renovación en conversación"]
AGNOS = [(2022, 8), (2023, 17), (2024, 25), (2025, 28), (2026, 22)]


def sin_tildes(txt):
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def fmt(d):
    return d.strftime("%d-%m-%Y")


def sumar_meses(d, n):
    m = d.month - 1 + n
    a = d.year + m // 12
    mes = m % 12 + 1
    return date(a, mes, min(d.day, calendar.monthrange(a, mes)[1]))


def dv_rut(num):
    s, f = 0, 2
    for c in reversed(str(num)):
        s += int(c) * f
        f = 2 if f == 7 else f + 1
    r = 11 - s % 11
    return "0" if r == 11 else "K" if r == 10 else str(r)


class Gen:
    def __init__(self, existentes_registro, existentes_clientes):
        self.r = random.Random(SEMILLA)
        self.vins = set(existentes_registro["VIN"])
        self.chasis_num = {v[-6:] for v in self.vins}
        self.ruts = set(existentes_clientes["RUT"])
        self.cdbs = set(existentes_clientes["CDB"].astype(str))
        self.nombres = set(existentes_clientes["Nombre"])
        self.cdb_flotas = set(existentes_registro["CDB FLOTA"])

    def pesos(self, lista):
        return self.r.choices([x[0] for x in lista], [x[1] for x in lista])[0]

    def cdb_nuevo(self, digitos, usados):
        while True:
            v = str(self.r.randint(10 ** (digitos - 1), 10 ** digitos - 1))
            if v not in usados:
                usados.add(v)
                return v

    def clientes(self, cantidad):
        out = []
        while len(out) < cantidad:
            pref = self.r.choice(list(PREFIJOS))
            lugar = self.r.choice(LUGARES)
            nombre = f"{pref} {lugar.upper()} {self.r.choice(SUFIJOS)}"
            if nombre in self.nombres:
                continue
            self.nombres.add(nombre)
            while True:
                n = self.r.randint(76_000_000, 79_999_999)
                rut = f"{n // 1_000_000}.{n // 1000 % 1000:03d}.{n % 1000:03d}-{dv_rut(n)}"
                if rut not in self.ruts:
                    self.ruts.add(rut)
                    break
            flotas = [(nombre, self.cdb_nuevo(10, self.cdb_flotas))]
            if self.r.random() < 0.06:
                flotas.append((f"{nombre} ({self.r.choice(['NORTE', 'SUR', 'CENTRO'])})",
                               self.cdb_nuevo(10, self.cdb_flotas)))
            comuna, region = self.r.choice(COMUNAS)
            out.append({
                "nombre": nombre, "rut": rut, "cdb": self.cdb_nuevo(8, self.cdbs), "flotas": flotas,
                "ejecutivo": self.pesos(EJECUTIVOS), "industria": self.r.choice(PREFIJOS[pref]),
                "comuna": comuna, "region": region, "dominio": sin_tildes(lugar.lower()).replace(" ", ""),
            })
        return out

    def vin(self):
        while True:
            num = f"{self.r.randint(0, 999999):06d}"
            if num in self.chasis_num:
                continue
            self.chasis_num.add(num)
            alfa = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
            v = (self.pesos(WMI) + "".join(self.r.choice(alfa) for _ in range(5)) + self.r.choice("0123456789X")
                 + self.r.choice("RSTV") + "E" + num)
            if v not in self.vins:
                self.vins.add(v)
                return v

    def fecha_inicio(self):
        a = self.pesos(AGNOS)
        ini, fin = date(a, 1, 1), min(date(a, 12, 31), HOY - timedelta(days=3))
        return ini + timedelta(days=self.r.randint(0, (fin - ini).days))

    def estado(self):
        return self.pesos(ESTADOS)

    def termino(self, inicio, dur):
        t = sumar_meses(inicio, dur)
        return t + timedelta(days=self.r.randint(-4, 4)) if self.r.random() < 0.12 else t

    def contrato(self, estado):
        """Devuelve (inicio, duracion, termino) coherentes con el estado."""
        for _ in range(60):
            inicio = self.fecha_inicio()
            dur = self.r.choice([12, 24, 36, 48, 60])
            t = self.termino(inicio, dur)
            if estado in ("Vencido", "Renovado"):
                if t <= HOY - timedelta(days=2):
                    return inicio, dur, t
            elif estado == "Baja":
                if inicio <= HOY - timedelta(days=70):
                    return inicio, dur, t
            elif t > HOY + timedelta(days=5):
                return inicio, dur, t
        inicio = HOY - timedelta(days=200)
        return inicio, 24, sumar_meses(inicio, 24)

    def fila(self, cli, flota, forma, estado, vin=None):
        r = self.r
        f = {c: "-" for c in COLUMNAS}
        f.update({"EJECUTIVO": cli["ejecutivo"], "RAZÓN SOCIAL": cli["nombre"], "RUT": cli["rut"],
                  "CDB COMERCIAL": cli["cdb"], "FLOTA VC": flota[0], "CDB FLOTA": flota[1],
                  "FLOTA VC 2": "", "INDUSTRIA": cli["industria"], "FORMA DE CONTRATO": forma,
                  "MODELO": self.pesos(MODELOS), "PAGO CM": "", "OBSERVACIONES": ""})
        vin = vin or self.vin()
        f["VIN"], f["CHASIS"] = vin, "E" + vin[-6:]
        sin_contrato = forma in ("Revisar", "Sin Contrato")
        facturacion = {"Provision": "INTERNO", "Provision +": "PROVISION +"}.get(forma)
        if forma in TIPO_CM:
            facturacion = "CM"
        elif sin_contrato:
            facturacion = "SIN REGISTRO"
        elif facturacion is None:
            facturacion = r.choices(["CLIENTE", "FACTURACIÓN MANUAL", "INTERNO"], [70, 27, 3])[0]
        f["TIPO DE FACTURACION"] = facturacion
        etapa = "COMERCIAL"
        creado = None

        if sin_contrato:
            f["ESTADO COMERCIAL"] = "Revisar"
            f["ESTADO DE ACTIVACIÓN ACTUAL"] = r.choices(["No aplica", "Conectado"], [60, 40])[0]
            f["OBSERVACIONES"] = "Cliente solicita revisar plan" if r.random() < 0.7 else ""
            creado = HOY - timedelta(days=r.randint(1, 90))
        elif forma == "Provision +":
            f["ESTADO COMERCIAL"] = "Vigente"
            f["TIPO DE SERVICIO"] = self.pesos(SERVICIOS)
            f["ESTADO DE ACTIVACIÓN ACTUAL"] = "Conectado" if r.random() < 0.95 else "Desconectado"
            f["ESTADO DE ENTREGA"] = fmt(self.fecha_inicio() - timedelta(days=r.randint(3, 30)))
            f["CONTRATO CREADO EN JUSTTIME"] = "Si" if r.random() < 0.9 else "-"
            creado = HOY - timedelta(days=r.randint(1, 400))
        else:
            f["ESTADO COMERCIAL"] = estado
            f["TIPO DE SERVICIO"] = self.pesos(SERVICIOS)
            if estado == "Activación Pendiente":
                etapa = "OPERACIONES"
                act = r.choices(["Activando", "No entregado", "Sin flota"], [40, 25, 35])[0]
                f["ESTADO DE ACTIVACIÓN ACTUAL"] = act
                f["DURACIÓN (MESES)"] = str(r.choice([12, 24, 36, 48, 60]))
                if act == "No entregado":
                    f["ESTADO DE ENTREGA"] = "No entregado"
                if act == "Sin flota":
                    f["FLOTA VC"], f["CDB FLOTA"] = "SIN FLOTA", "-"
                if r.random() < 0.25:
                    ini = HOY - timedelta(days=r.randint(1, 35))
                    f["INICIO CONTRATO"] = fmt(ini)
                    f["TÉRMINO CONTRATO"] = fmt(self.termino(ini, int(f["DURACIÓN (MESES)"])))
                    if act == "Activando":
                        f["ESTADO DE ENTREGA"] = fmt(ini - timedelta(days=r.randint(2, 20)))
                creado = HOY - timedelta(days=r.randint(1, 60))
                if r.random() < 0.4:
                    f["OBSERVACIONES"] = "Pendiente confirmar contacto"
            else:
                inicio, dur, term = self.contrato(estado)
                f["INICIO CONTRATO"], f["DURACIÓN (MESES)"], f["TÉRMINO CONTRATO"] = fmt(inicio), str(dur), fmt(term)
                ini_mes = inicio.replace(day=1)
                f["INICIO"], f["TERMINO"] = fmt(ini_mes), fmt(sumar_meses(ini_mes, dur))
                f["ESTADO DE ENTREGA"] = fmt(inicio - timedelta(days=r.randint(2, 25)))
                creado = inicio
                if estado in ("Vigente", "Baja Solicitada"):
                    f["ESTADO DE ACTIVACIÓN ACTUAL"] = r.choices(
                        ["Conectado", "Activando", "No aplica"], [96, 2, 2])[0]
                    if estado == "Baja Solicitada":
                        f["FECHA DE BAJA"] = fmt(HOY - timedelta(days=r.randint(1, 120)))
                elif estado == "Baja":
                    f["ESTADO DE ACTIVACIÓN ACTUAL"] = "Desconectado"
                    tope = min(term, HOY)
                    dias = max(1, (tope - inicio).days - 45)
                    f["FECHA DE BAJA"] = fmt(inicio + timedelta(days=45 + r.randint(0, dias)))
                else:
                    f["ESTADO DE ACTIVACIÓN ACTUAL"] = r.choices(["Conectado", "Desconectado"], [80, 20])[0]
                if r.random() < 0.55 and estado in ("Vigente", "Baja Solicitada"):
                    f["CONTRATO CREADO EN JUSTTIME"] = "Si"
                elif r.random() < 0.06:
                    f["CONTRATO CREADO EN JUSTTIME"] = r.choice(["Pendiente", "Eliminar", "Revisar pago"])
                if r.random() < 0.4:
                    f["OBSERVACIONES"] = r.choice(OBS)
                if forma in TIPO_CM:
                    tipo = TIPO_CM[forma]
                    f["N CONTRATO 3PC"] = str(r.randint(300_000_000, 399_999_999))
                    f["FECHA INICIO CM"], f["FECHA TERMINO CM"] = fmt(inicio), fmt(term)
                    f["TIPO DE CM"] = tipo
                    f["ESTADO DEL CM"] = {"Baja": "Terminated", "Vencido": "Expired", "Renovado": "Expired"}.get(
                        estado, "Running")
                    f["PAGO CM"] = str(r.choice(PAGO_CM[tipo]))
        if forma in ("Provision +",) or sin_contrato:
            etapa = "COMERCIAL"
        elif etapa == "COMERCIAL" and r.random() < 0.08:
            etapa = "OPERACIONES"
        f["ETAPA GESTIÓN"] = etapa
        f["PERIODO INTERNO"] = f"{MESES[creado.month - 1]} - {creado.year}"
        return f


COLUMNAS = ["ID", "EJECUTIVO", "PERIODO INTERNO", "RAZÓN SOCIAL", "VIN", "CHASIS", "MODELO", "FLOTA VC", "RUT",
            "CDB COMERCIAL", "CDB FLOTA", "FLOTA VC 2", "FORMA DE CONTRATO", "TIPO DE SERVICIO", "INICIO CONTRATO",
            "DURACIÓN (MESES)", "TÉRMINO CONTRATO", "ESTADO COMERCIAL", "FECHA DE BAJA", "TIPO DE FACTURACION",
            "CONTRATO CREADO EN JUSTTIME", "INICIO", "TERMINO", "ESTADO DE ACTIVACIÓN ACTUAL", "ESTADO DE ENTREGA",
            "OBSERVACIONES", "N CONTRATO 3PC", "FECHA INICIO CM", "FECHA TERMINO CM", "TIPO DE CM", "ESTADO DEL CM",
            "PAGO CM", "INDUSTRIA", "ETAPA GESTIÓN"]


def tamanos_clientes(r, total):
    tams = []
    while sum(tams) < total:
        tams.append(max(1, int(r.lognormvariate(2.2, 1.1))))
    tams[-1] -= sum(tams) - total
    return [t for t in tams if t > 0]


def main(carpeta, total=12000):
    ruta_reg = os.path.join(carpeta, "Registro Maestro.csv")
    with open(ruta_reg, "rb") as fh:
        con_bom = fh.read(3) == b"\xef\xbb\xbf"
    enc = "utf-8-sig" if con_bom else "utf-8"
    reg = pd.read_csv(ruta_reg, dtype=str, keep_default_na=False, encoding=enc)
    ruta_bbdd = os.path.join(carpeta, "BBDD CLIENTES CM.xlsx")
    hojas_bbdd = pd.read_excel(ruta_bbdd, sheet_name=None)
    base_cli = hojas_bbdd["Clientes Camiones"]
    if len(reg) >= total:
        print("Ya hay", len(reg), "filas; nada que hacer.")
        return
    g = Gen(reg, base_cli)
    nuevas_unidades = int((total - len(reg)) / 1.017)
    tams = tamanos_clientes(g.r, nuevas_unidades)
    clientes = g.clientes(len(tams))

    filas = []
    for cli, n in zip(clientes, tams):
        for _ in range(n):
            flota = cli["flotas"][-1] if len(cli["flotas"]) > 1 and g.r.random() < 0.4 else cli["flotas"][0]
            forma = g.pesos(FORMAS)
            estado = g.estado()
            f = g.fila(cli, flota, forma, estado)
            filas.append(f)
            if (f["ESTADO COMERCIAL"] == "Vigente" and f["INICIO CONTRATO"] != "-" and g.r.random() < 0.04):
                ini_act = pd.to_datetime(f["INICIO CONTRATO"], format="%d-%m-%Y").date()
                previo = g.fila(cli, flota, forma, "Baja", vin=f["VIN"])
                dur = g.r.choice([12, 24])
                p_ini = sumar_meses(ini_act, -(dur + g.r.randint(0, 6)))
                p_fin = sumar_meses(p_ini, dur)
                previo.update({"INICIO CONTRATO": fmt(p_ini), "DURACIÓN (MESES)": str(dur),
                               "TÉRMINO CONTRATO": fmt(p_fin), "FECHA DE BAJA": fmt(p_fin - timedelta(days=g.r.randint(0, 20))),
                               "INICIO": fmt(p_ini.replace(day=1)), "TERMINO": fmt(sumar_meses(p_ini.replace(day=1), dur)),
                               "ESTADO DE ACTIVACIÓN ACTUAL": "Desconectado",
                               "PERIODO INTERNO": f"{MESES[p_ini.month - 1]} - {p_ini.year}"})
                if previo["FECHA INICIO CM"] != "-":
                    previo.update({"FECHA INICIO CM": fmt(p_ini), "FECHA TERMINO CM": fmt(p_fin),
                                   "ESTADO DEL CM": "Terminated"})
                filas.append(previo)
    g.r.shuffle(filas)
    id_ini = int(pd.to_numeric(reg["ID"], errors="coerce").max()) + 1
    for i, f in enumerate(filas):
        f["ID"] = str(id_ini + i)
    nuevo = pd.DataFrame(filas, columns=COLUMNAS)
    pd.concat([reg, nuevo], ignore_index=True).to_csv(ruta_reg, index=False, encoding=enc)

    # Clientes (ambas hojas)
    cols = list(base_cli.columns)
    regs = []
    for c in clientes:
        n = int(c["cdb"]) % 1000
        regs.append({
            "CDB": int(c["cdb"]), "Fecha de creación": fmt(date(2015, 1, 1) + timedelta(days=g.r.randint(0, 4000))),
            "Nº de Organización": g.r.randint(100000, 999999), "Nº Parma": g.r.randint(1000, 9999),
            "Nombre": c["nombre"], "RUT": c["rut"], "Teléfono": f"+56 2 {g.r.randint(2000, 2999)} {g.r.randint(1000, 9999)}",
            "Correo electrónico": f"contacto@{c['dominio']}.cl", "Categoría": "Cliente", "Área de negocio": "Camiones",
            "Responsable": c["ejecutivo"], "Número GDS Fusion": g.r.randint(10000, 99999),
            "Dirección": f"Av. Ficticia {n + g.r.randint(1, 5000)}", "Column14": float("nan"),
            "Column15": float("nan"), "Código Postal": float("nan"), "Ciudad": c["comuna"], "Región": c["region"],
            "Comuna": c["comuna"], "País": "Chile"})
    extra = pd.DataFrame(regs, columns=cols)
    for k, h in hojas_bbdd.items():
        if list(h.columns) == cols:
            hojas_bbdd[k] = pd.concat([h, extra], ignore_index=True)
    with pd.ExcelWriter(ruta_bbdd) as w:
        for k, h in hojas_bbdd.items():
            h.to_excel(w, sheet_name=k, index=False)

    # Contactos de flota (la mayoría de las flotas, no todas)
    ruta_ct = os.path.join(carpeta, "contactos.xlsx")
    ct = pd.read_excel(ruta_ct)
    sig = int(ct["ID"].max()) + 1
    nuevos = []
    for c in clientes:
        for nombre_f, cdb_f in c["flotas"]:
            if g.r.random() > 0.85:
                continue
            for _ in range(2 if g.r.random() < 0.25 else 1):
                nom, ape = g.r.choice(NOMBRES), g.r.choice(APELLIDOS)
                nuevos.append({
                    "ID": sig, "CDB": int(cdb_f), "Flota": nombre_f, "Nombre": nom, "Apellidos": ape,
                    "Correo electrónico": f"{sin_tildes(nom).lower()}.{sin_tildes(ape).lower()}@{c['dominio']}.cl",
                    "Número móvil": f"+56 9 {g.r.randint(5000, 9999)} {g.r.randint(1000, 9999)}",
                    "Rol": "Administrador de flota", "Fecha de extracción": "12-10-2026 09:30:00"})
                sig += 1
    pd.concat([ct, pd.DataFrame(nuevos, columns=list(ct.columns))], ignore_index=True).to_excel(ruta_ct, index=False)

    # Provisiones: tres meses por unidad vigente en Provision / Provision +
    ruta_pv = os.path.join(carpeta, "provisionFelipe.xlsx")
    hojas_pv = pd.read_excel(ruta_pv, sheet_name=None)
    pv = hojas_pv["Prov"]
    uf = float(pv["UF"].iloc[0]) if len(pv) else 39215.57
    prov = []
    sel = nuevo[nuevo["FORMA DE CONTRATO"].isin(["Provision", "Provision +"])
                & (nuevo["ESTADO COMERCIAL"] == "Vigente")]
    for _, u in sel.iterrows():
        plan = u["TIPO DE SERVICIO"] if u["TIPO DE SERVICIO"] in PRECIOS_PLAN else "Medio"
        for per in ("2026 - Agosto", "2026 - Septiembre", "2026 - Octubre"):
            prov.append({"AÑO - MES": per, "VIN": u["VIN"], "CLIENTE": u["RAZÓN SOCIAL"], "EJECUTIVO": u["EJECUTIVO"],
                         "OBSERVACIONES": float("nan"), "DYNAFLEET": PRECIOS_PLAN[plan], "Cantidad de Meses": 1,
                         "Plan": plan, "Monto Provisionado": float(PRECIOS_PLAN[plan]),
                         "Valor Plan": float(PRECIOS_PLAN[plan]), "VAR": 0.0, "UF": uf, "ID CONTRATO": int(u["ID"])})
    hojas_pv["Prov"] = pd.concat([pv, pd.DataFrame(prov, columns=list(pv.columns))], ignore_index=True)
    with pd.ExcelWriter(ruta_pv) as w:
        for k, h in hojas_pv.items():
            h.to_excel(w, sheet_name=k, index=False)
    print(f"{carpeta}: contratos {len(reg)} -> {len(reg) + len(nuevo)}, clientes +{len(clientes)}, "
          f"contactos +{len(nuevos)}, provisiones +{len(prov)}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12000)
