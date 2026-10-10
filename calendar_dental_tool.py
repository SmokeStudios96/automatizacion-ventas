import os
import datetime
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from database import SessionLocal

# Cargar variables de entorno del archivo .env
load_dotenv()

# Configuración de Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'google_credentials.json'

CALENDAR_ID = os.getenv(
    'GOOGLE_CALENDAR_ID', 
    'e4764b4b66087030b1f300da41c0813607582b569c2a297618fa04714ce121ce@group.calendar.google.com'
)

# Definición del staff, especialidades y horarios de atención
PROFESIONALES = {
    "roberto soto": {"especialidad": "Odontología General", "dias": [0, 1, 2, 3, 4], "inicio": 9, "fin": 17},
    "camila valenzuela": {"especialidad": "Ortodoncia", "dias": [1, 3], "inicio": 10, "fin": 18},
    "ignacio morales": {"especialidad": "Periodoncia", "dias": [0, 2, 4], "inicio": 14, "fin": 19},
    "valentina paz": {"especialidad": "Odontopediatría", "dias": [0, 1, 2, 3], "inicio": 9, "fin": 14}
}


def get_calendar_service():
    """Autentica y devuelve el cliente de la API de Google Calendar."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Archivo de credenciales '{CREDENTIALS_FILE}' no encontrado.")
    
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build('calendar', 'v3', credentials=creds)


def registrar_en_supabase(nombre_paciente: str, telefono_paciente: str, profesional: str, especialidad: str, fecha_hora_inicio: datetime.datetime):
    """Inserta o actualiza el paciente y guarda la cita en el esquema clinica de Supabase."""
    db = SessionLocal()
    try:
        clean_phone = telefono_paciente.replace("+", "").strip()
        
        # 1. Verificar o registrar al paciente en clinica.pacientes
        sql_paciente_check = "SELECT id FROM clinica.pacientes WHERE telefono = :tel LIMIT 1;"
        res_paciente = db.execute(sql_paciente_check, {"tel": clean_phone}).fetchone()
        
        if not res_paciente:
            sql_insert_paciente = "INSERT INTO clinica.pacientes (telefono, nombre) VALUES (:tel, :nom);"
            db.execute(sql_insert_paciente, {"tel": clean_phone, "nom": nombre_paciente})
        
        # 2. Registrar la cita en clinica.citas
        sql_insert_cita = """
            INSERT INTO clinica.citas (telefono_paciente, nombre_paciente, profesional, especialidad, fecha_hora_inicio, estado)
            VALUES (:tel, :nom, :prof, :esp, :fhi, 'confirmada');
        """
        db.execute(sql_insert_cita, {
            "tel": clean_phone,
            "nom": nombre_paciente,
            "prof": profesional,
            "esp": especialidad,
            "fhi": fecha_hora_inicio
        })
        
        db.commit()
        print("✅ Cita y paciente registrados exitosamente en el esquema clinica de Supabase.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al guardar en Supabase (Esquema clinica): {e}")
    finally:
        db.close()


def get_available_slots(date_str: str) -> str:
    """
    Consulta los eventos agendados para una fecha específica (formato YYYY-MM-DD).
    Retorna un resumen de los bloques ocupados para determinar disponibilidad de los boxes.
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
            return f"No hay citas agendadas para el día {date_str}. Ambos boxes se encuentran completamente disponibles."

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

        return f"Citas agendadas el {date_str}:\n" + "\n".join(busy_slots)

    except Exception as e:
        print(f"❌ Error al consultar Google Calendar: {e}")
        return f"Error al consultar el calendario: {str(e)}"


def book_dental_appointment(nombre_paciente: str, profesional_solicitado: str, fecha_hora_inicio: str, telefono_paciente: str = "Desconocido") -> str:
    """
    Agenda una cita dental validando turnos del profesional y la concurrencia de los 2 boxes físicos.
    - nombre_paciente: Nombre completo del paciente.
    - profesional_solicitado: Nombre del especialista (Dr. Roberto Soto, Dra. Camila Valenzuela, etc.)
    - fecha_hora_inicio: Fecha y hora en formato ISO (ej: '2026-10-12T10:00:00')
    - telefono_paciente: Teléfono de contacto de WhatsApp del paciente.
    """
    if not CALENDAR_ID:
        return "No se pudo agendar: Calendario no configurado."

    try:
        prof_key = profesional_solicitado.lower().strip()
        for prefix in ["dr.", "dra.", "doctor", "doctora"]:
            if prof_key.startswith(prefix):
                prof_key = prof_key.replace(prefix, "").strip()

        if prof_key not in PROFESIONALES:
            return (
                f"Lo siento, no encontré al especialista '{profesional_solicitado}'. "
                "Contamos con:\n"
                "- Dr. Roberto Soto (Odontología General)\n"
                "- Dra. Camila Valenzuela (Ortodoncia)\n"
                "- Dr. Ignacio Morales (Periodoncia)\n"
                "- Dra. Valentina Paz (Odontopediatría)"
            )

        info_prof = PROFESIONALES[prof_key]
        
        if not fecha_hora_inicio.endswith("-03:00") and not fecha_hora_inicio.endswith("Z"):
            start_iso_str = fecha_hora_inicio + "-03:00"
        else:
            start_iso_str = fecha_hora_inicio

        start_time = datetime.datetime.fromisoformat(start_iso_str)
        
        if start_time.weekday() not in info_prof["dias"]:
            dias_texto = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            dias_atencion = ", ".join([dias_texto[d] for d in info_prof["dias"]])
            return f"El/La profesional {profesional_solicitado.title()} no atiende los días {start_time.strftime('%A')}. Sus días de atención son: {dias_atencion}."

        if not (info_prof["inicio"] <= start_time.hour < info_prof["fin"]):
            return f"El horario seleccionado está fuera del turno del profesional (Atiende de {info_prof['inicio']}:00 a {info_prof['fin']}:00 hrs)."

        service = get_calendar_service()
        end_time = start_time + datetime.timedelta(minutes=45)

        time_min = start_time.strftime('%Y-%m-%dT%H:%M:%S') + '-03:00'
        time_max = end_time.strftime('%Y-%m-%dT%H:%M:%S') + '-03:00'
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True
        ).execute()
        
        citas_existentes = events_result.get('items', [])
        
        if len(citas_existentes) >= 2:
            return "Lo sentimos, en este bloque horario los dos boxes de la clínica se encuentran ocupados. ¿Te gustaría revisar disponibilidad en un horario cercano?"

        # Crear el evento en Google Calendar
        summary = f"[{info_prof['especialidad']}] - {profesional_solicitado.title()} / Paciente: {nombre_paciente}"
        description = f"Cita dental agendada vía bot.\nEspecialidad: {info_prof['especialidad']}\nEspecialista: {profesional_solicitado.title()}\nTeléfono: {telefono_paciente}"

        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'America/Santiago'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'America/Santiago'},
        }

        created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        
        # Registrar respaldo en Supabase (Esquema clinica)
        registrar_en_supabase(
            nombre_paciente=nombre_paciente,
            telefono_paciente=telefono_paciente,
            profesional=profesional_solicitado.title(),
            especialidad=info_prof['especialidad'],
            fecha_hora_inicio=start_time
        )
        
        return (
            f"✅ ¡Cita agendada con éxito!\n"
            f"- *Especialista:* {profesional_solicitado.title()} ({info_prof['especialidad']})\n"
            f"- *Fecha y Hora:* {start_time.strftime('%d/%m/%Y a las %H:%M hrs')}\n"
            f"- *Paciente:* {nombre_paciente}"
        )

    except Exception as e:
        print(f"❌ Error al agendar cita dental: {e}")
        return f"Error al procesar la reserva: {str(e)}"