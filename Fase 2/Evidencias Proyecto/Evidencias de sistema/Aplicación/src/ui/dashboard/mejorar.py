"""Segundo tablero del Dashboard de Volvo Connect: dónde actuar.
Junta en dos cajas a quién contactar (clientes con camiones desconectados o sin servicio, y la cartera de cada
ejecutivo) y mantiene dónde se pierden clientes y cómo conecta cada servicio. Reutiliza los filtros, el cálculo
y el estilo de cajas del Resumen; solo cambia lo que se arma y se pinta."""
import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout

from src.services import dashboard_services as servicio
from src.ui.administracion import estilo as admin_estilo
from src.ui.dashboard import (APAGADO, MARINO, ROJO, TONO_CLARO, TONO_MEDIO, BarrasFuga, BarrasServicio, _etiqueta, _leyenda,
                              _num, _pct)
from src.ui.dashboard.contactar import AMBAR, BarrasEjecutivoContacto, FugaConDetalle, TablaClientes
from src.ui.dashboard.resumen import DashboardResumenModule, _KpiCaja


class DashboardMejorarModule(DashboardResumenModule):
    """Tablero de acción: a quién contactar, dónde se pierden clientes y cómo conecta cada servicio."""

    FORMA_ESQUELETO = 'tablero'
    FILAS = 6
    FILAS_FUGA = 5
    ALTO_FILA_MIN = 16
    NO_CUENTAN_FACTURACION = ('sin registro', 'sin definir', 'no definida', 'no definido')

    def _armar_tablero(self, lay):
        # Las metas no se usan en este tablero
        self._seccion_metas.hide()
        self._segmento_fuga = "FACTURACION"
        self._vista_clientes = "TODOS"
        self._ejecutivo_filtrado = None
        self._filas_clientes = []
        self._contacto = {'filas': [], 'con_desconectados': 0, 'para_ofrecer': 0, 'ya_usan': 0, 'ambas': 0}
        lay.addLayout(self._crear_kpis_mejorar())
        rejilla = QGridLayout()
        rejilla.setSpacing(10)
        rejilla.setContentsMargins(0, 0, 0, 0)
        for c in (0, 1):
            rejilla.setColumnStretch(c, 1)
            rejilla.setRowStretch(c, 1)
        rejilla.addWidget(self._flexible(self._crear_caja_clientes()), 0, 0)
        rejilla.addWidget(self._flexible(self._crear_caja_ejecutivo()), 0, 1)
        rejilla.addWidget(self._flexible(self._crear_caja_fuga()), 1, 0)
        rejilla.addWidget(self._flexible(self._crear_caja_servicio()), 1, 1)
        lay.addLayout(rejilla, 1)

    # ------------------------------------------------------------------ cajas
    def _crear_caja_clientes(self):
        caja = admin_estilo.caja_con_encabezado(
            "cajaClientesMejorar", "Clientes a contactar",
            "Camiones desconectados o sin servicio por cliente.")
        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 10, 14, 10)
        cuerpo.setSpacing(6)
        caja.fila_cab.addWidget(self._segmentos((("TODOS", "Todos"), ("REC", "Recuperar"), ("OFR", "Ofrecer")),
                                                self._elegir_vista_clientes))
        self.btn_filtro_ejecutivo = QPushButton()
        self.btn_filtro_ejecutivo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filtro_ejecutivo.setToolTip("Quitar el filtro por ejecutivo")
        self.btn_filtro_ejecutivo.setStyleSheet(
            "QPushButton { background: #E3E8F1; color: #1B2B4E; border: none; border-radius: 10px; padding: 6px 12px; "
            "font-size: 12px; font-weight: 700; } QPushButton:hover { background: #D5DDEB; }")
        self.btn_filtro_ejecutivo.clicked.connect(lambda: self._elegir_ejecutivo(None))
        self.btn_filtro_ejecutivo.hide()
        fila_leyenda = QHBoxLayout()
        fila_leyenda.addWidget(_leyenda((("Conectados", MARINO), ("Desconectados", ROJO), ("Sin servicio", AMBAR))))
        fila_leyenda.addStretch(1)
        fila_leyenda.addWidget(self.btn_filtro_ejecutivo)
        cuerpo.addLayout(fila_leyenda)
        self.tabla_clientes = TablaClientes()
        self.tabla_clientes.fila_clicada.connect(self._clic_cliente)
        cuerpo.addWidget(self.tabla_clientes, 1)
        caja.cuerpo.addLayout(cuerpo)
        return caja.marco

    def _crear_caja_ejecutivo(self):
        caja = admin_estilo.caja_con_encabezado(
            "cajaEjecutivoMejorar", "Por ejecutivo",
            "Unidades de cada uno y cuántos clientes tiene por contactar.")
        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 10, 14, 10)
        cuerpo.setSpacing(6)
        cuerpo.addWidget(_leyenda((("Conectados", MARINO), ("Por conectar", TONO_CLARO), ("Desconectados", ROJO), ("Sin servicio", AMBAR))))
        self.grafico_ejecutivo = BarrasEjecutivoContacto()
        self.grafico_ejecutivo.ejecutivo_clicado.connect(self._elegir_ejecutivo)
        cuerpo.addWidget(self.grafico_ejecutivo, 1)
        caja.cuerpo.addLayout(cuerpo)
        return caja.marco

    def _crear_caja_fuga(self):
        caja = admin_estilo.caja_con_encabezado(
            "cajaFugaMejorar", "Dónde se pierden clientes",
            "Porcentaje de camiones desconectados en cada grupo.")
        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 10, 14, 10)
        cuerpo.setSpacing(8)
        caja.fila_cab.addWidget(self._segmentos((("FACTURACION", "Facturación"), ("MODELO", "Modelo")), self._elegir_segmento_fuga))
        self.grafico_fuga = FugaConDetalle()
        cuerpo.addWidget(self.grafico_fuga, 1)
        caja.cuerpo.addLayout(cuerpo)
        return caja.marco

    def _crear_caja_servicio(self):
        caja = admin_estilo.caja_con_encabezado(
            "cajaServicioMejorar", "Conexión por tipo de servicio",
            "Porcentaje conectado de cada servicio, del que mejor conecta al que peor.")
        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 10, 14, 10)
        cuerpo.setSpacing(8)
        cuerpo.addWidget(_leyenda((("Plan Básico", TONO_CLARO), ("Plan Medio", TONO_MEDIO), ("Plan Full", MARINO))))
        self.grafico_servicio = BarrasServicio()
        cuerpo.addWidget(self.grafico_servicio, 1)
        caja.cuerpo.addLayout(cuerpo)
        return caja.marco

    # ------------------------------------------------------------------ elecciones
    def _elegir_vista_clientes(self, clave):
        self._vista_clientes = clave
        self._pintar_clientes()

    def _elegir_segmento_fuga(self, clave):
        self._segmento_fuga = clave
        self._pintar_fuga()

    def _elegir_ejecutivo(self, nombre):
        """Presionar el mismo ejecutivo otra vez quita el filtro."""
        self._ejecutivo_filtrado = None if nombre in (None, self._ejecutivo_filtrado) else nombre
        self._pintar_clientes()

    def _clic_cliente(self, indice):
        if 0 <= indice < len(self._filas_clientes):
            fila = self._filas_clientes[indice]
            abrir = getattr(self.window(), 'abrir_cliente_en_general', None)
            if abrir is not None and fila.get('clave') and fila['vins']:
                abrir(fila['clave'], list(fila['vins']), fila['nombre'])
            else:
                self._abrir_en_flotas(fila['vins'], fila['nombre'])

    # ------------------------------------------------------------------ pintado
    def _repintar(self, *_):
        activos = self._filtros_activos()
        filtrando = any(v for k, v in activos.items() if k not in ("SIN_PRUEBAS", "SIN_NO_APLICA"))
        self.btn_quitar.setEnabled(filtrando)
        self._pintar_aplicados()
        if self._panorama is None:
            for caja in self._km.values():
                caja.poner("—")
            self.grafico_servicio.set_datos([])
            self.grafico_ejecutivo.set_datos([])
            self.tabla_clientes.set_datos([])
            self.grafico_fuga.set_datos([], 0)
            self._unidades_actuales = None
            return
        sub = servicio.filtrar_panorama(self._panorama, **activos)
        self._panorama_vista = sub
        unidades = sub['unidades']
        self._unidades_actuales = unidades
        # Los camiones sin servicio suelen ser No aplica: para ofrecerles el servicio se miran siempre
        potenciales = servicio.unidades_filtradas(self._panorama, **dict(activos, SIN_NO_APLICA=False))
        self._contacto = servicio.clientes_a_contactar(unidades, potenciales)
        self._ejecutivos = servicio.por_ejecutivo_contactar(unidades, potenciales, self._contacto['filas'], limite=self.FILAS)
        self._pintar_franja(servicio.calcular_kpis(unidades), unidades)
        self.grafico_servicio.set_datos(servicio.conexion_por_servicio(unidades))
        self._pintar_ejecutivos()
        self._pintar_clientes()
        self._pintar_fuga()
        self._fijar_altos()

    def _pintar_ejecutivos(self):
        for e in self._ejecutivos:
            e['clientes'] = [(f['nombre'], f['accion']) for f in self._contacto['filas'] if e['ejecutivo'] in f['ejecutivos']]
        self.grafico_ejecutivo.set_datos(self._ejecutivos)

    def _pintar_clientes(self):
        filas = self._contacto['filas']
        if self._vista_clientes == "REC":
            filas = [f for f in filas if f['des']]
        elif self._vista_clientes == "OFR":
            filas = [f for f in filas if f['sin']]
        if self._ejecutivo_filtrado:
            filas = [f for f in filas if self._ejecutivo_filtrado in f['ejecutivos']]
        self._filas_clientes = filas[:self.FILAS]
        self.tabla_clientes.set_datos(self._filas_clientes)
        self.grafico_ejecutivo.seleccion = self._ejecutivo_filtrado
        self.grafico_ejecutivo.update()
        self.btn_filtro_ejecutivo.setVisible(self._ejecutivo_filtrado is not None)
        if self._ejecutivo_filtrado:
            self.btn_filtro_ejecutivo.setText(f"{self._ejecutivo_filtrado}  ✕")

    def _pintar_fuga(self):
        unidades = self._unidades_actuales
        if unidades is None:
            self.grafico_fuga.set_datos([], 0)
            return
        fuga = servicio.fuga_por_segmento(unidades, self._segmento_fuga, limite=self.FILAS_FUGA)
        self.grafico_fuga.set_datos(fuga['filas'], fuga['promedio'])

    def _fijar_altos(self):
        """Las listas y gráficos tienen un alto mínimo pequeño: las filas se ajustan al espacio de la caja, así
        que el tablero cabe sin scroll y las cuatro cajas quedan del mismo tamaño."""
        for lista in (self.tabla_clientes, self.grafico_ejecutivo):
            lista.setMinimumHeight(lista.ALTO_CABECERA + self.FILAS * 26)
        self.grafico_fuga.setMinimumHeight(self.grafico_fuga.ALTO_CABECERA + self.FILAS_FUGA * self.ALTO_FILA_MIN)
        self.grafico_servicio.setMinimumHeight(self.FILAS * self.ALTO_FILA_MIN)

    def _crear_kpis_mejorar(self):
        """Cinco KPI con el mismo diseño que los del Resumen; los que cuentan camiones por contactar abren sus flotas."""
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self._km = {}
        self._km_vins = {}
        for clave, titulo in (("des", "Desconectados"), ("recuperar", "Por recuperar"), ("ofrecer", "Para ofrecer el servicio"),
                              ("usan", "Clientes que usan el servicio"), ("pierde", "Facturación que más pierde")):
            caja = _KpiCaja(titulo)
            caja.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            fila.addWidget(caja, 1)
            self._km[clave] = caja
        for clave, titulo in (("recuperar", "Unidades desconectadas"), ("ofrecer", "Unidades para ofrecer el servicio"),
                              ("usan", "Clientes que usan el servicio")):
            self._km[clave].clicked.connect(lambda c=clave, t=titulo: self._abrir_en_flotas(self._km_vins[c](), t))
        return fila

    def _pintar_franja(self, k, unidades):
        desglose = dict(k['desglose_no_conectada'])
        desconectadas = desglose.get('DESCONECTADO', 0)
        universo = k['universo'] or 1
        self._km["des"].poner(_num(desconectadas), f"{_pct(desconectadas / universo)} del total")
        self._km["des"].setToolTip("Camiones desconectados de todos los que muestran los filtros.")

        filas = self._contacto['filas']

        def vins_de(condicion):
            return lambda: sorted({v for f in filas if condicion(f) for v in f['vins']})

        n_des, n_ofrecer, n_usan = sum(f['des'] for f in filas), sum(f['sin'] for f in filas), self._contacto['ya_usan']
        self._km_vins = {"recuperar": vins_de(lambda f: f['des']), "ofrecer": vins_de(lambda f: f['sin']),
                         "usan": vins_de(lambda f: f['des'] and f['con'])}
        for clave, n, sub, ayuda in (
                ("recuperar", n_des, "de clientes a contactar", "Camiones desconectados de los clientes a contactar."),
                ("ofrecer", n_ofrecer, "camiones sin servicio", "Camiones sin servicio de Volvo Connect de los clientes a contactar."),
                ("usan", n_usan, "y aún tienen camiones conectados",
                 "Clientes con camiones desconectados que todavía tienen camiones conectados: ya usan Volvo Connect y una llamada puede bastar.")):
            caja = self._km[clave]
            caja.poner(_num(n), sub)
            if n:
                caja.set_clicable(ayuda + " Haz clic para ver sus flotas.")
            else:
                caja.setToolTip(ayuda)
                caja._clicable = False
                caja.unsetCursor()
        definidas = [f for f in servicio.fuga_por_segmento(unidades, 'FACTURACION')['filas']
                     if f['nombre'].casefold() not in self.NO_CUENTAN_FACTURACION]
        peor = definidas[0] if definidas else None
        if peor:
            self._km["pierde"].poner(_pct(peor['tasa']), f"Facturación {peor['nombre']}")
            self._km["pierde"].setToolTip(f"Facturación que más pierde (sin contar Sin registro): {_pct(peor['tasa'])} "
                                          "de sus camiones están desconectados.")
        else:
            self._km["pierde"].poner("—", "sin facturaciones para comparar")