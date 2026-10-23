"""PDF 'Detalle de facturación EDP – Volvo Connect' de una flota de
Facturación Manual. Se arma con QTextDocument/QPrinter (sin navegador)."""
import html
import os
from datetime import datetime

from PyQt6.QtCore import QMarginsF, QUrl
from PyQt6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument, QImage
from PyQt6.QtPrintSupport import QPrinter

from src.services.facturacion_manual_service import MESES_ES

_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "logo_volvo.png")

FIRMA = [
    "Javiera González Maldonado", "Encargada de Servicios Conectados", "Volvo Chile",
    "Soluciones de Transporte de Carga | Conectividad", "Tel. +56934128411",
    "Av. Pdte Eduardo Frei Montalva 8691 | Quilicura, Santiago de Chile",
]


def _n2(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _clp(valor):
    return "$ " + f"{int(valor):,}".replace(",", ".")


def construir_html(datos):
    """`datos`: cliente, anio, mes (1-12 del período), fecha_emision (str),
    uf, unidades_n, neto_uf, neto_clp y filas = [(flota, rut, vin, plan, precio_uf)]."""
    esc = html.escape
    mes, anio = datos["mes"], datos["anio"]
    filas = "".join(
        f"<tr><td>{esc(str(f))}</td><td align='center' nowrap>{esc(str(r))}</td>"
        f"<td align='center' nowrap>{esc(str(v))}</td>"
        f"<td align='center' nowrap>{esc(str(p))}</td><td align='center'>{_n2(pr) if pr is not None else '-'}</td></tr>"
        for f, r, v, p, pr in datos["filas"])
    if datos.get("precio_fijo"):
        precios = (
            f"<tr><td>Modalidad</td><td align='right'>Precio fijo mensual</td></tr>"
            f"<tr><td>Precio Neto Total CLP</td><td align='right'>{_clp(datos['neto_clp'])}</td></tr>")
    else:
        precios = (
            f"<tr><td>{datos.get('uf_etiqueta', 'UF hoy')}</td><td align='right'>{_n2(datos['uf']) if datos['uf'] else '-'}</td></tr>"
            f"<tr><td>Precio Neto Total UF</td><td align='right'>{_n2(datos['neto_uf'])}</td></tr>"
            f"<tr><td>Precio Neto Total CLP</td><td align='right'>{_clp(datos['neto_clp']) if datos['neto_clp'] is not None else '-'}</td></tr>")
    resumen = (
        "<table border='1' cellspacing='0' cellpadding='3' width='55%'>"
        "<tr><td colspan='2' bgcolor='#000000' align='center'><font color='#ffffff'><b>Resumen precios</b></font></td></tr>"
        f"<tr><td>Unidades conectadas</td><td align='right'>{datos['unidades_n']}</td></tr>"
        f"{precios}"
        "</table>")
    detalle = (
        "<table border='1' cellspacing='0' cellpadding='3' width='100%'>"
        "<tr bgcolor='#000000'>"
        + "".join(f"<td align='center' width='{w}%'><font color='#ffffff'><b>{t}</b></font></td>"
                  for t, w in (("Flota", 27), ("Rut", 16), ("VIN", 28), ("Plan", 14), ("Precio UF", 15)))
        + f"</tr>{filas}</table>")
    firma = "<br>".join(f"<b>{esc(t)}</b>" if i < 2 else esc(t) for i, t in enumerate(FIRMA))
    return f"""<html><body style="font-family: Arial; font-size: 10pt;">
<p align="center"><img src="logo" height="34"></p>
<h3 align="center">DETALLE DE FACTURACIÓN EDP – VOLVO CONNECT</h3>
<p align="center"><b>Periodo: {MESES_ES[mes - 1]} {anio}</b></p>
<p><b>Cliente:</b> {esc(datos['cliente'])}<br><b>Fecha de emisión:</b> {esc(datos['fecha_emision'])}</p>
<p>Estimado(a) cliente:</p>
<p>Junto con saludar, por medio del presente se informa el detalle correspondiente a la facturación de los servicios EDP asociados al período de <b>{MESES_ES[mes - 1].lower()} de {anio}</b>.</p>
<p><b>1.&nbsp;&nbsp;Detalle de Servicios Facturados</b></p>
{resumen}
<p><b>2.&nbsp;&nbsp;Detalle</b></p>
{detalle}
<p><b>3. Consideraciones</b></p>
<ul>
<li>Los precios indicados corresponden a los servicios efectivamente prestados durante el período señalado.</li>
<li>El impuesto al valor agregado (IVA) se aplica conforme a la normativa vigente en Chile.</li>
<li>Este documento tiene carácter informativo y respalda el detalle de la facturación emitida.</li>
</ul>
<p>Sin otro particular, saluda atentamente,</p>
<p>{firma}</p>
</body></html>"""


def generar_pdf(ruta, datos):
    """Escribe el PDF en `ruta` (A4, márgenes 14/16 mm)."""
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Arial", 10))
    if os.path.exists(_LOGO):
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl("logo"), QImage(_LOGO))
    doc.setHtml(construir_html(datos))
    impresora = QPrinter(QPrinter.PrinterMode.HighResolution)
    impresora.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    impresora.setOutputFileName(ruta)
    impresora.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                        QMarginsF(16, 14, 16, 14), QPageLayout.Unit.Millimeter))
    doc.print(impresora)


def nombre_sugerido(cliente, anio=None, mes=None):
    """Nombre del archivo: la razón social tal como viene; solo se cambian los
    caracteres que Windows no admite en un nombre de archivo."""
    limpio = "".join(" " if c in '\\/:*?"<>|' else c for c in str(cliente))
    limpio = " ".join(limpio.split()).strip(" .") or "Detalle de facturación"
    return f"{limpio}.pdf"


def fecha_emision(hoy=None):
    return (hoy or datetime.now()).strftime("%d-%m-%Y")
