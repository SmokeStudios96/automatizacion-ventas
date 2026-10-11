import os
import json
import datetime
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from database import SessionLocal

# Cargar variables de entorno del archivo .env
load_dotenv()

# Configuración de Google Calendar para Estética
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'google_credentials.json'

CALENDAR_ID = os.getenv(
    'GOOGLE_CALENDAR_ID_ESTETICA', 
    'e4764b4b66087030b1f300da41c0813607582b569c2a297618fa04714ce121ce@group.calendar.google.com'
)

# Definición de servicios, duraciones (en minutos) y horarios de Ona Songailaite
SERVICIOS_ESTETICA = {
    "microblading": {"duracion": 120, "precio": 150000, "dias": [1, 2, 3, 4, 5, 6], "inicio": 10, "fin": 19},
    "micropigmentacion labios": {"duracion": 150, "precio": 160000, "dias": [1, 2, 3, 4, 5, 6], "inicio": 10, "fin": 19},
    "efecto polvo cejas": {"duracion": 120, "precio": 140000, "dias": [1, 2, 3, 4, 5, 6], "inicio": 10, "fin": 19},
    "repaso cejas": {"duracion": 90, "precio": 50000, "dias": [1, 2, 3, 4, 5, 6], "inicio": 10, "fin": 19}
}


def get_calendar_service():
    """Autentica y devuelve el cliente de la API de Google Calendar."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"⚠️ Error cargando credenciales de Calendar desde env: {e}")

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Archivo de credenciales '{CREDENTIALS_FILE}' no encontrado.")
    
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build('calendar', 'v3', credentials=creds)


def registrar_en_supabase_estetica(nombre_cliente: str, telefono_cliente: str, servicio: str, fecha_hora_inicio: datetime.datetime):
    """Inserta o actualiza el cliente y guarda la cita en el esquema estetica_pmu de Supabase."""
    db = SessionLocal()
    try:
        clean_phone = telefono_cliente.replace("+", "").strip()
        
        # 1. Verificar o registrar al cliente en estetica_pmu.clientes
        sql_cliente_check = "SELECT id FROM estetica_pmu.clientes WHERE telefono = :tel LIMIT 1;"
        res_cliente = db.execute(sql_cliente_check, {"tel": clean_phone}).fetchone()
        
        if not res_cliente:
            sql_insert_cliente = "INSERT INTO estetica_pmu.clientes (telefono, nombre) VALUES (:tel, :nom);"
            db.execute(sql_insert_cliente, {"tel": clean_phone, "nom": nombre_cliente})
        
        # 2. Registrar la cita en estetica_pmu.citas
        sql_insert_cita = """
            INSERT INTO estetica_pmu.citas (telefono_cliente, nombre_cliente, servicio, fecha_hora_inicio, estado)
            VALUES (:tel, :nom, :serv, :fhi, 'confirmada');
        """
        db.execute(sql_insert_cita, {
            "tel": clean_phone,
            "nom": nombre_cliente,
            "serv": servicio,
            "fhi": fecha_hora_inicio
        })
        
        db.commit()
        print("✅ Cita y cliente registrados exitosamente en el esquema estetica_pmu de Supabase.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al guardar en Supabase (Esquema estetica_pmu): {e}")
    finally:
        db.close()


def get_available_slots_estetica(date_str: str) -> str:
    """
    Consulta los eventos agendados en el estudio para una fecha específica (formato YYYY-MM-DD).
    """
    if not CALENDAR_ID:
        return "El servicio de calendario no está configurado actualmente."

    try:
        service = get_calendar_service()
        
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
            return f"El estudio de Ona no tiene citas agendadas para el día {date_str}. Hay total disponibilidad."

        busy_slots = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'Ocupado')
            
            if 'T' in start:
                start_formatted = start.split('T')[1][:5]
                end_formatted = end.split('T')[1][:5]
                busy_slots.append(f"- De {start_formatted} a {end_formatted} hrs: {summary}")
            else:
                busy_slots.append(f"- Todo el día: {summary}")

        return f"Citas agendadas para el {date_str}:\n" + "\n".join(busy_slots)

    except Exception as e:
        print(f"❌ Error al consultar Google Calendar: {e}")
        return f"Error al consultar el calendario: {str(e)}"


def book_estetica_appointment(nombre_cliente: str, servicio_solicitado: str, fecha_hora_inicio: str, telefono_cliente: str = "Desconocido") -> str:
    """
    Agenda una cita de estética validando disponibilidad con el calendario de Google y guardando en Supabase.
    - nombre_cliente: Nombre completo del cliente.
    - servicio_solicitado: Nombre del procedimiento (Microblading, Micropigmentacion Labios, etc.)
    - fecha_hora_inicio: Fecha y hora en formato ISO (ej: '2026-10-15T11:00:00')
    - telefono_cliente: Teléfono de contacto de WhatsApp del cliente.
    """
    if not CALENDAR_ID:
        return "No se pudo agendar: Calendario no configurado."

    try:
        serv_key = servicio_solicitado.lower().strip()
        
        # Coincidencia flexible básica de servicios
        match_serv = None
        for key in SERVICIOS_ESTETICA:
            if key in serv_key or serv_key in key:
                match_serv = key
                break

        if not match_serv:
            return (
                f"Lo siento, no encontré el servicio '{servicio_solicitado}'. "
                "Los procedimientos disponibles con Ona Songailaite son:\n"
                "- Microblading\n"
                "- Micropigmentación de Labios\n"
                "- Efecto Polvo Cejas\n"
                "- Repaso de Cejas"
            )

        info_serv = SERVICIOS_ESTETICA[match_serv]
        
        if not fecha_hora_inicio.endswith("-03:00") and not fecha_hora_inicio.endswith("Z"):
            start_iso_str = fecha_hora_inicio + "-03:00"
        else:
            start_iso_str = fecha_hora_inicio

        start_time = datetime.datetime.fromisoformat(start_iso_str)
        
        if start_time.weekday() not in info_serv["dias"]:
            return "Lo sentimos, el estudio de Ona no atiende los días domingo."

        if not (info_serv["inicio"] <= start_time.hour < info_serv["fin"]):
            return f"El horario seleccionado está fuera del horario de atención (Atendemos de {info_serv['inicio']}:00 a {info_serv['fin']}:00 hrs)."

        service = get_calendar_service()
        duracion_min = info_serv["duracion"]
        end_time = start_time + datetime.timedelta(minutes=duracion_min)

        # Crear el evento en Google Calendar
        summary = f"[ESTETICA] {match_serv.title()} - Cliente: {nombre_cliente}"
        description = f"Cita de estética agendada vía bot.\nServicio: {match_serv.title()}\nTeléfono: {telefono_cliente}"

        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'America/Santiago'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'America/Santiago'},
        }

        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        
        # Registrar respaldo en Supabase (Esquema estetica_pmu)
        registrar_en_supabase_estetica(
            nombre_cliente=nombre_cliente,
            telefono_cliente=telefono_cliente,
            servicio=match_serv.title(),
            fecha_hora_inicio=start_time
        )
        
        return (
            f"✨ ¡Cita agendada con éxito para Ona Songailaite!\n"
            f"- *Servicio:* {match_serv.title()}\n"
            f"- *Fecha y Hora:* {start_time.strftime('%d/%m/%Y a las %H:%M hrs')}\n"
            f"- *Cliente:* {nombre_cliente}"
        )

    except Exception as e:
        print(f"❌ Error al agendar cita de estética: {e}")
        return f"Error al procesar la reserva: {str(e)}"