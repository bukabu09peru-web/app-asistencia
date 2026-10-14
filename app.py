import csv
import io
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st


st.set_page_config(
    page_title="Reporte de asistencia",
    page_icon="🕒",
    layout="wide",
)

ZONA = ZoneInfo("America/Lima")
BASE = Path(__file__).resolve().parent / "asistencia.db"


def conectar():
    return sqlite3.connect(BASE, timeout=20)


def inicializar():
    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS asistencia (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                persona TEXT NOT NULL,
                entrada TEXT NOT NULL,
                salida TEXT
            )
        """)
        conexion.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS una_entrada_abierta
            ON asistencia(persona)
            WHERE salida IS NULL
        """)


def registrar(nombre, movimiento):
    nombre = " ".join(nombre.split())
    persona = nombre.casefold()

    with conectar() as conexion:
        # Evita que dos registros simultáneos se crucen.
        conexion.execute("BEGIN IMMEDIATE")

        abierto = conexion.execute(
            """
            SELECT id FROM asistencia
            WHERE persona = ? AND salida IS NULL
            """,
            (persona,),
        ).fetchone()

        ahora = datetime.now(ZONA).isoformat(timespec="seconds")

        if movimiento == "Entrada":
            if abierto:
                return False, "Este nombre ya tiene una entrada sin salida."

            conexion.execute(
                """
                INSERT INTO asistencia (nombre, persona, entrada)
                VALUES (?, ?, ?)
                """,
                (nombre, persona, ahora),
            )
        else:
            if not abierto:
                return False, "Primero debes registrar una entrada."

            conexion.execute(
                "UPDATE asistencia SET salida = ? WHERE id = ?",
                (ahora, abierto[0]),
            )

    hora = datetime.fromisoformat(ahora).strftime("%H:%M:%S")
    return True, f"{movimiento} registrada para {nombre} a las {hora}."


def consultar(desde, hasta):
    with conectar() as conexion:
        return conexion.execute(
            """
            SELECT nombre, entrada, salida
            FROM asistencia
            WHERE substr(entrada, 1, 10) BETWEEN ? AND ?
            ORDER BY entrada DESC
            """,
            (desde.isoformat(), hasta.isoformat()),
        ).fetchall()


inicializar()

st.title("🕒 Reporte de asistencia")
st.caption("Registro de entrada y salida · Hora de Perú")
st.info(
    "Versión de prueba: descarga tus reportes. "
    "Los datos locales pueden perderse en Streamlit Cloud."
)

registro, reporte = st.tabs(["Registrar asistencia", "Ver reporte"])

with registro:
    st.subheader("Registrar entrada o salida")

    with st.form("registro_asistencia", clear_on_submit=False):
        nombre = st.text_input(
            "Nombre completo",
            placeholder="Ejemplo: Ana López",
            max_chars=120,
        )
        movimiento = st.radio(
            "¿Qué deseas registrar?",
            ["Entrada", "Salida"],
            horizontal=True,
        )
        guardar = st.form_submit_button("Registrar")

    if guardar:
        if not nombre.strip():
            st.error("Escribe el nombre completo.")
        else:
            correcto, mensaje = registrar(nombre, movimiento)
            if correcto:
                st.success(mensaje)
            else:
                st.warning(mensaje)

    st.caption(
        "Para registrar la salida, escribe el mismo nombre de la entrada. "
        "Esta versión identifica a cada persona por su nombre."
    )

with reporte:
    st.subheader("Consultar asistencia")
    hoy = datetime.now(ZONA).date()

    columna1, columna2 = st.columns(2)
    with columna1:
        desde = st.date_input("Desde", value=hoy)
    with columna2:
        hasta = st.date_input("Hasta", value=hoy)

    buscar = st.text_input("Filtrar por nombre (opcional)")

    if desde > hasta:
        st.error("La fecha inicial no puede ser mayor que la final.")
    else:
        filas = consultar(desde, hasta)
        datos = []

        for nombre, entrada, salida in filas:
            if buscar.strip().casefold() not in nombre.casefold():
                continue

            inicio = datetime.fromisoformat(entrada)
            fin = datetime.fromisoformat(salida) if salida else None

            duracion = ""
            if fin:
                segundos = int((fin - inicio).total_seconds())
                horas, resto = divmod(segundos, 3600)
                minutos = resto // 60
                duracion = f"{horas:02d}:{minutos:02d}"

            datos.append({
                "Nombre": nombre,
                "Fecha entrada": inicio.strftime("%d/%m/%Y"),
                "Hora entrada": inicio.strftime("%H:%M:%S"),
                "Fecha salida": fin.strftime("%d/%m/%Y") if fin else "",
                "Hora salida": fin.strftime("%H:%M:%S") if fin else "",
                "Tiempo registrado": duracion,
                "Estado": "Completado" if fin else "Sin salida",
            })

        st.metric("Registros encontrados", len(datos))

        if datos:
            st.dataframe(datos, hide_index=True, use_container_width=True)

            archivo = io.StringIO()
            escritor = csv.DictWriter(
                archivo,
                fieldnames=list(datos[0].keys()),
                delimiter=";",
            )
            escritor.writeheader()

            # Evita interpretar nombres como fórmulas al abrir en Excel.
            for dato in datos:
                copia = dato.copy()
                if copia["Nombre"].startswith(("=", "+", "-", "@")):
                    copia["Nombre"] = "'" + copia["Nombre"]
                escritor.writerow(copia)

            st.download_button(
                "📥 Descargar reporte para Excel",
                data=archivo.getvalue().encode("utf-8-sig"),
                file_name=f"asistencia_{desde}_{hasta}.csv",
                mime="text/csv",
            )
        else:
            st.info("No hay registros para este filtro.")

    st.caption(
        "El reporte filtra por la fecha de entrada. "
        "El tiempo registrado incluye todo el intervalo, sin descontar descansos."
    )
