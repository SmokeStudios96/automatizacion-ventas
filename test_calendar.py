from dotenv import load_dotenv
import os

# Cargar variables de entorno desde el archivo .env
load_dotenv()

from agent_whatsapp import obtener_bloques_ocupados, agendar_cita_calendar
from datetime import datetime, timedelta, timezone

# 1. Probar lectura de disponibilidad para hoy
print("🔍 Probando lectura del calendario para hoy...")
resumen_hoy = obtener_bloques_ocupados("2026-10-08")
print(resumen_hoy)

# 2. Probar agendamiento de prueba para mañana a las 15:00 hrs
print("\n📅 Agendando cita de prueba para mañana...")
tz_chile = timezone(timedelta(hours=-3))
manana = (datetime.now(tz_chile) + timedelta(days=1)).strftime("%Y-%m-%d")

inicio_iso = f"{manana}T15:00:00-03:00"
fin_iso = f"{manana}T16:00:00-03:00"

resultado_agendamiento = agendar_cita_calendar(
    resumen="Demo Smoke Studios (Test IA)",
    inicio_iso=inicio_iso,
    fin_iso=fin_iso,
    descripcion="Cita de prueba generada desde el script de Python"
)
print(resultado_agendamiento)