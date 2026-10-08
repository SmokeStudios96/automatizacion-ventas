import os
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from agno.tools import tool

# Cargar variables de entorno del archivo .env
load_dotenv()

# Configuración de Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'google_credentials.json'

# Se lee desde el .env o toma el ID directamente como respaldo
CALENDAR_ID = os.getenv(
    'GOOGLE_CALENDAR_ID', 
    'e4764b4b66087030b1f300da41c0813607582b569c2a297618fa04714ce121ce@group.calendar.google.com'
)


def get_calendar_service():
    """Autentica y devuelve el cliente de la API de Google Calendar."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Archivo de credenciales '{CREDENTIALS_FILE}' no encontrado.")
    
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build('calendar', 'v3', credentials=creds)


@tool
def get_available_slots(date_str: str) -> str:
    """
    Consulta los eventos agendados para una fecha específica (formato YYYY-MM-DD).
    Retorna un resumen de los bloques ocupados para determinar disponibilidad.
    """
    if not CALENDAR_ID:
        return "El servicio de calendario no está configurado actualmente."

    try:
        service = get_calendar_service()
        
        # Ajuste de horario para Chile Continental (UTC-3)
        time_min = f"{date_str}T00:00:00-03:00"
        time_max = f"{date_str}T23:59:59-03:00"

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        if not events:
            return f"No hay citas agendadas para el día {date_str}. Todo el día está disponible."

        busy_slots = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'Ocupado')
            
            # Limpiar el formato ISO para legibilidad
            if 'T' in start:
                start_formatted = start.split('T')[1][:5]
                end_formatted = end.split('T')[1][:5]
                busy_slots.append(f"- De {start_formatted} a {end_formatted} hrs: {summary}")
            else:
                busy_slots.append(f"- Todo el día: {summary}")

        return f"Citas ocupadas el {date_str}:\n" + "\n".join(busy_slots)

    except Exception as e:
        print(f"❌ Error al consultar Google Calendar: {e}")
        return f"Error al consultar el calendario: {str(e)}"


@tool
def book_appointment(summary: str, start_time: str, end_time: str, description: str = "") -> str:
    """
    Crea una nueva cita en Google Calendar.
    - summary: Nombre de la cita/cliente (ej: 'Reunión Smoke Studios - Juan Pérez')
    - start_time: Fecha y hora de inicio en formato ISO (ej: '2026-10-09T10:00:00-03:00')
    - end_time: Fecha y hora de término en formato ISO (ej: '2026-10-09T11:00:00-03:00')
    - description: Detalles adicionales (ej: 'Teléfono o especificaciones del proyecto')
    """
    if not CALENDAR_ID:
        return "No se pudo agendar: Calendario no configurado."

    try:
        service = get_calendar_service()
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'America/Santiago'},
            'end': {'dateTime': end_time, 'timeZone': 'America/Santiago'},
        }

        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return f"✅ Cita agendada exitosamente: {created_event.get('htmlLink')}"

    except Exception as e:
        print(f"❌ Error al agendar en Google Calendar: {e}")
        return f"Error al crear la cita: {str(e)}"