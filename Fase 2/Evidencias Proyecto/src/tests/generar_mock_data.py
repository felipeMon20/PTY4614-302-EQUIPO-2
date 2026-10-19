import os
import pandas as pd
from datetime import datetime

def generar_excels_prueba(base_dir=None):
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")
    base_dir = os.path.abspath(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    print(f"Generando archivos de prueba milimétricos en:\n{base_dir}\n")

    # ========================================================
    # 1. PRUEBAS_FM (Comercial) - Estructura Clónica Exacta
    # ========================================================
    columnas_comercial = [
        'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'FLOTA VC 2', 'EJECUTIVO',
        'RAZÓN SOCIAL', 'RUT', 'CDB', 'INDUSTRIA', 'FORMA DE CONTRATO',
        'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'TIPO DE FACTURACION',
        'CONTRATO CREADO EN JUSTTIME', 'ESTADO DE ACTIVACIÓN ACTUAL',
        'ESTADO DE ENTREGA', 'FECHA DE BAJA', 'INICIO CONTRATO', 'DURACIÓN (MESES)',
        'TÉRMINO CONTRATO', 'PERIODO INTERNO', 'INICIO', 'TERMINO', 'N CONTRATO 3PC',
        'FECHA INICIO CM', 'FECHA TERMINO CM',
        'TIPO DE CM', 'ESTADO DEL CM', 'PAGO CM', 'FECHA TÉRMINO CM', 'TIPO DE FACTURACIÓN',
        'ETAPA GESTIÓN', 'OBSERVACIONES'
    ]
    
    data_comercial = {col: [] for col in columnas_comercial}
    
    # Camión 1: Activo y Conectado
    data_comercial['VIN'].append('YV2TEST0000900054')
    data_comercial['CHASIS'].append('0900054')
    data_comercial['MODELO'].append('FH')
    data_comercial['FLOTA VC'].append('EMPRESA PRUEBA S.A.')
    data_comercial['EJECUTIVO'].append('JUAN PEREZ')
    data_comercial['RAZÓN SOCIAL'].append('EMPRESA PRUEBA S.A.')
    data_comercial['RUT'].append('31.708.930-0')
    data_comercial['CDB'].append('10001')
    data_comercial['INDUSTRIA'].append('Minería')
    data_comercial['FORMA DE CONTRATO'].append('CMG')
    data_comercial['TIPO DE SERVICIO'].append('FULL')
    data_comercial['ESTADO COMERCIAL'].append('Vigente')
    data_comercial['ESTADO DE ACTIVACIÓN ACTUAL'].append('CONECTADO')
    data_comercial['ESTADO DE ENTREGA'].append('01-08-2026')
    data_comercial['INICIO CONTRATO'].append('01-08-2026')
    data_comercial['DURACIÓN (MESES)'].append('12')
    data_comercial['TÉRMINO CONTRATO'].append('01-08-2027')
    data_comercial['PERIODO INTERNO'].append('Agosto - 2026')
    data_comercial['INICIO'].append('01-08-2026')
    data_comercial['TERMINO'].append('01-08-2027')
    data_comercial['ESTADO DEL CM'].append('RUNNING')
    data_comercial['PAGO CM'].append(150000)

    # Camión 2: Vencido y Desconectado
    data_comercial['VIN'].append('YV2TEST0000900055')
    data_comercial['CHASIS'].append('0900055')
    data_comercial['MODELO'].append('FMX')
    data_comercial['FLOTA VC'].append('TRANSPORTES TEST')
    data_comercial['EJECUTIVO'].append('MARIA GOMEZ')
    data_comercial['RAZÓN SOCIAL'].append('TRANSPORTES TEST')
    data_comercial['RUT'].append('32.287.017-8')
    data_comercial['CDB'].append('10002')
    data_comercial['INDUSTRIA'].append('Construcción')
    data_comercial['FORMA DE CONTRATO'].append('CMB')
    data_comercial['TIPO DE SERVICIO'].append('MEDIO')
    data_comercial['ESTADO COMERCIAL'].append('Vencido')
    data_comercial['ESTADO DE ACTIVACIÓN ACTUAL'].append('DESCONECTADO')
    data_comercial['ESTADO DE ENTREGA'].append('-')
    data_comercial['FECHA DE BAJA'].append('15-08-2026')
    data_comercial['INICIO CONTRATO'].append('15-08-2025')
    data_comercial['DURACIÓN (MESES)'].append('12')
    data_comercial['TÉRMINO CONTRATO'].append('15-08-2026')
    data_comercial['PERIODO INTERNO'].append('Agosto - 2025')
    data_comercial['INICIO'].append('15-08-2025')
    data_comercial['TERMINO'].append('15-08-2026')
    data_comercial['ESTADO DEL CM'].append('EXPIRED')
    data_comercial['PAGO CM'].append(85000)
    
    for col in columnas_comercial:
        while len(data_comercial[col]) < 2: data_comercial[col].append('')

    df_comercial = pd.DataFrame(data_comercial)

    # ========================================================
    # 2. PROVISIONES (provisionContratos) - 3 hojas estrictas
    # ========================================================
    df_prov = pd.DataFrame({
        'AÑO - MES': ['2026 - Agosto', '2026 - Agosto'],
        'VIN': ['YV2TEST0000900054', 'YV2TEST0000900055'],
        'CLIENTE': ['EMPRESA PRUEBA S.A.', 'TRANSPORTES TEST'],
        'EJECUTIVO': ['JUAN PEREZ', 'MARIA GOMEZ'],
        'OBSERVACIONES': ['', 'Vencido'],
        'DYNAFLEET': [150000, 85000],
        'Cantidad de Meses': [1, 1],
        'Plan': ['FULL', 'MEDIO'],
        'Monto Provisionado': [150000, 85000],
        'Valor Plan': [150000, 85000],
        'VAR': [0, 0]
    })
    df_prov_vars = pd.DataFrame({'Variable': ['UF', 'CIV'], 'Valor': [38000.5, 0.5]})
    df_prov_planes = pd.DataFrame({
        'Plan': ['BASICO', 'MEDIO', 'FULL', 'FULL + CIV', 'MEDIO + CIV'], 
        'Multiplicador UF': [0.5, 1.0, 1.5, 2.0, 1.5], 
        'Precio': [19000, 38000, 57000, 76000, 57000]
    })

    # ========================================================
    # 3. CONTACTOS (contactos.xlsx) - [INCLUYE COLUMNA ID]
    # ========================================================
    df_contactos = pd.DataFrame({
        'ID': [1, 2],
        'CDB': ['10001', '10002'],
        'Flota': ['EMPRESA PRUEBA S.A.', 'TRANSPORTES TEST'],
        'Nombre': ['Pedro', 'Ana'],
        'Apellidos': ['Prueba', 'Test'],
        'Correo electrónico': ['pedro@prueba.example', 'ana@test.example'],
        'Número móvil': ['+56 9 1111 1111', '+56 9 2222 2222'],
        'Rol': ['Administrador de flota', 'Administrador de flota'],
        'Fecha de extracción': ['24-08-2026 10:00:00', '24-08-2026 10:00:00']
    })

    # ========================================================
    # 4. INSTALACIONES (Instalaciones.xlsx)
    # ========================================================
    df_instalaciones = pd.DataFrame({
        'RUT': ['31.708.930-0', '32.287.017-8'], 
        'VIN': ['YV2TEST0000900054', 'YV2TEST0000900055'], 
        'CHASSIS': ['0900054', '0900055'], 
        'NOMBRE CONTRATO': ['0900054 EMPRESA PRUEBA S.A.', '0900055 TRANSPORTES TEST'], 
        'RAZON SOCIAL': ['EMPRESA PRUEBA S.A.', 'TRANSPORTES TEST'], 
        'DIRECCIÓN': ['Av. Falsa 123', 'Calle Verdadera 456'], 
        'COMUNA': ['Santiago', 'Quilicura'], 
        'ADMINISTRADOR DE FLOTA': ['Pedro Prueba', 'Ana Test'], 
        'CORREO ADMINISTRADOR': ['pedro@prueba.example', 'ana@test.example'], 
        'TELÉFONO ADMINISTRADOR': ['+56 9 1111 1111', '+56 9 2222 2222'], 
        'INICIO': ['01-08-2026', '15-08-2025'], 
        'MESES': ['12', '12'], 
        'TERMINO': ['01-08-2027', '15-08-2026']
    })

    # ========================================================
    # 5. REGISTRO ELIMINADO (RegistroEliminado.xlsx)
    # ========================================================
    columnas_eliminados = ['FECHA Y HORA DE ELIMINACIÓN', 'MÓDULO'] + columnas_comercial
    df_eliminados = pd.DataFrame(columns=columnas_eliminados)

    # ========================================================
    # 6. HISTORIAL ENVIOS (Historial_Envios_VC.xlsx)
    # ========================================================
    df_historial = pd.DataFrame(columns=[
        'id_envio', 'fecha_hora', 'tipo_correo', 'razon_social', 'chasis', 'destinatario', 'estado', 'asunto'
    ])

    # --- GUARDADO ESTRUCTURADO CON OPENPYXL ---
    with pd.ExcelWriter(os.path.join(base_dir, "PruebasFM_Test.xlsx"), engine='openpyxl') as writer:
        df_comercial.to_excel(writer, sheet_name='BBDD (2)', index=False)
        
    with pd.ExcelWriter(os.path.join(base_dir, "provisionContratos_Test.xlsx"), engine='openpyxl') as writer:
        df_prov.to_excel(writer, sheet_name='Prov', index=False)
        df_prov_vars.to_excel(writer, sheet_name='Variables', index=False)
        df_prov_planes.to_excel(writer, sheet_name='Planes', index=False)
        
    with pd.ExcelWriter(os.path.join(base_dir, "contactos_Test.xlsx"), engine='openpyxl') as writer:
        df_contactos.to_excel(writer, sheet_name='Administradores', index=False)
        
    with pd.ExcelWriter(os.path.join(base_dir, "Instalaciones_Test.xlsx"), engine='openpyxl') as writer:
        df_instalaciones.to_excel(writer, sheet_name='Agosto - 2026', index=False)
        
    with pd.ExcelWriter(os.path.join(base_dir, "RegistroEliminado_Test.xlsx"), engine='openpyxl') as writer:
        df_eliminados.to_excel(writer, sheet_name='Sheet1', index=False)
        
    with pd.ExcelWriter(os.path.join(base_dir, "Historial_Envios_VC_Test.xlsx"), engine='openpyxl') as writer:
        df_historial.to_excel(writer, sheet_name='Sheet1', index=False)

    print("¡Fase 1 completada con éxito! Las 6 BBDD clónicas están listas para ser torturadas por el motor de pruebas.")

if __name__ == "__main__":
    generar_excels_prueba()