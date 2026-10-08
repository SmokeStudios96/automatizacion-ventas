import os
import time
import requests
from typing import Dict, Tuple
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from google import genai
from google.genai import types

from database import SessionLocal, NegocioConfig, Producto, HistorialMensaje, sincronizar_chat_supabase

# ------------------------------------------------------------------------------
# 1. Configuración de Variables de Entorno y Google Calendar
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_secret_token")
CONTACTO_HUMANO = os.environ.get("CONTACTO_HUMANO", "+56939270181")

# Google Calendar Specs
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
CREDENTIALS_FILE = "google_credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Control de Rate Limiting en memoria por número de teléfono
user_message_history: Dict[str, list] = {}
MAX_CARACTERES_ENTRADA = 1000
MAX_MENSAJES_RAFAGA = 5
VENTANA_TIEMPO_SEG = 30


def get_calendar_service():
    """Autentica y retorna la instancia del servicio de Google Calendar."""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"⚠️ Archivo de credenciales '{CREDENTIALS_FILE}' no encontrado.")
        return None
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def obtener_bloques_ocupados(fecha_str: str) -> str:
    """
    Consulta los eventos ocupados para una fecha específica (formato YYYY-MM-DD).
    """
    try:
        service = get_calendar_service()
        if not service or not GOOGLE_CALENDAR_ID:
            return "El servicio de calendario no está configurado actualmente."

        time_min = f"{fecha_str}T00:00:00-03:00"
        time_max = f"{fecha_str}T23:59:59-03:00"

        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        if not events:
            return f"No hay agendamientos previos para el día {fecha_str}. Todo el día está disponible."

        bloques = []
        for event in events:
            inicio = event["start"].get("dateTime", event["start"].get("date"))
            fin = event["end"].get("dateTime", event["end"].get("date"))
            resumen = event.get("summary", "Ocupado")
            
            # Formatear horas si viene en formato completo ISO
            if "T" in inicio:
                inicio_h = inicio.split("T")[1][:5]
                fin_h = fin.split("T")[1][:5]
                bloques.append(f"- De {inicio_h} a {fin_h} hrs ({resumen})")
            else:
                bloques.append(f"- Todo el día: {resumen}")

        return f"Bloques ocupados el {fecha_str}:\n" + "\n".join(bloques)
    except Exception as e:
        print(f"❌ Error al consultar Calendar: {e}")
        return f"No se pudo consultar el calendario: {e}"


def agendar_cita_calendar(resumen: str, inicio_iso: str, fin_iso: str, descripcion: str = "") -> str:
    """
    Agenda una cita directamente en Google Calendar.
    - inicio_iso / fin_iso formato: "YYYY-MM-DDTHH:MM:SS-03:00"
    """
    try:
        service = get_calendar_service()
        if not service or not GOOGLE_CALENDAR_ID:
            return "No se pudo agendar: Calendario no configurado."

        event = {
            "summary": resumen,
            "description": descripcion,
            "start": {"dateTime": inicio_iso, "timeZone": "America/Santiago"},
            "end": {"dateTime": fin_iso, "timeZone": "America/Santiago"},
        }

        created_event = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID, body=event
        ).execute()

        return f"✅ Cita agendada con éxito. Confirmación: {created_event.get('htmlLink')}"
    except Exception as e:
        print(f"❌ Error al agendar en Calendar: {e}")
        return f"Error al registrar la cita: {e}"


# ------------------------------------------------------------------------------
# 2. Utilidades del Negocio, Historial y Rate Limiter
# ------------------------------------------------------------------------------
def validar_mensaje_entrante(telefono: str, texto_mensaje: str) -> Tuple[bool, str]:
    """Valida la longitud del mensaje y aplica Rate Limiting por número de teléfono."""
    ahora = time.time()
    
    if len(texto_mensaje) > MAX_CARACTERES_ENTRADA:
        return False, "Tu mensaje es muy extenso. Por favor, envía una consulta más breve para ayudarte de inmediato."
    
    if telefono not in user_message_history:
        user_message_history[telefono] = []
        
    user_message_history[telefono] = [
        t for t in user_message_history[telefono] if ahora - t < VENTANA_TIEMPO_SEG
    ]
    
    if len(user_message_history[telefono]) >= MAX_MENSAJES_RAFAGA:
        return False, "Has enviado varios mensajes muy rápido. Por favor, aguarda unos segundos antes de escribir de nuevo."
        
    user_message_history[telefono].append(ahora)
    return True, ""


def obtener_datos_negocio():
    """Retorna los datos de negocio y catálogo de Smoke Studios."""
    db = SessionLocal()
    try:
        negocio = db.query(NegocioConfig).first()
        if negocio:
            productos = db.query(Producto).filter(Producto.negocio_id == negocio.id).all()
            catalogo = "\n".join([
                f"- {p.nombre} (SKU: {p.sku}): ${p.precio:,.0f} CLP | Categoría: {p.categoria}"
                for p in productos
            ]) if productos else ""
            return {
                "nombre_negocio": negocio.nombre_negocio,
                "persona_ia": negocio.persona_ia,
                "reglas_atencion": negocio.reglas_atencion,
                "telefono_contacto": negocio.telefono_contacto or CONTACTO_HUMANO,
                "catalogo_texto": catalogo
            }
    except Exception as e:
        print(f"⚠️ Error leyendo base local: {e}")
    finally:
        db.close()

    # Configuración por defecto de Smoke Studios
    return {
        "nombre_negocio": "Smoke Studios",
        "persona_ia": "Ejecutivo Comercial Virtual",
        "reglas_atencion": (
            "1. Eres un consultor tecnológico experto, amable y transparente.\n"
            "2. Responde sobre desarrollo web Next.js, agentes IA, dashboards en Supabase y flujos n8n.\n"
            "3. Ofrece agendar reuniones demostrativas o de levantamiento técnico según la disponibilidad.\n"
            "4. Si el cliente solicita cotización a medida, descuento o hablar con una persona, deriva al contacto humano."
        ),
        "telefono_contacto": CONTACTO_HUMANO,
        "catalogo_texto": (
            "- Desarrollo Web Next.js 15: Desde $490.000 CLP | Entrega rápida y SEO optimizado\n"
            "- Agente IA WhatsApp 24/7: Desde $350.000 CLP | Integrado a Supabase y CRM\n"
            "- Automatización n8n / Make: Desde $180.000 CLP | Conexión de formularios y pagos\n"
            "- Dashboard Privado Smoke Studios: Incluido con el servicio de IA"
        )
    }


def guardar_historial(telefono: str, remitente: str, mensaje: str):
    """Guarda el mensaje en PostgreSQL."""
    db = SessionLocal()
    try:
        nuevo = HistorialMensaje(cliente_telefono=telefono, remitente=remitente, mensaje=mensaje)
        db.add(nuevo)
        db.commit()
    except Exception as e:
        print(f"❌ Error guardando historial: {e}")
    finally:
        db.close()


def obtener_contexto_horario():
    """Calcula el horario para Chile Continental (UTC-3)."""
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)

    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    fecha_iso = ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M")

    es_dia_laboral = ahora.weekday() < 5
    hora_decimal = ahora.hour + ahora.minute / 60.0
    esta_abierto = es_dia_laboral and (9.0 <= hora_decimal < 18.5)

    estado = "HORARIO COMERCIAL ACTIVO" if esta_abierto else "FUERA DE HORARIO COMERCIAL (Atención 24/7)"
    return f"Fecha actual: {fecha_iso} ({dia_str}). Hora actual: {hora_str} hrs. Estado: {estado}."


def detectar_solicitud_humana(texto: str) -> bool:
    """Verifica si el usuario solicitó explícitamente a un agente humano."""
    terminos = [
        "humano", "persona", "ejecutivo", "asesor", "hablar con alguien",
        "llámame", "llamada", "reunión", "descuento", "cotización personalizada"
    ]
    t = texto.lower()
    return any(term in t for term in terminos)


# ------------------------------------------------------------------------------
# 3. Envío a WhatsApp y Consulta a Gemini con Calendar
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient, text):
    """Envía el mensaje de texto al usuario por WhatsApp Cloud API."""
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)

    if not token:
        print("❌ Error: WHATSAPP_TOKEN no está definido en las variables de entorno.")
        return

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        print(f"❌ Error al enviar mensaje por Meta ({resp.status_code}): {resp.text}")


def ask_agent(user_text: str, telefono_cliente: str, nombre_cliente: str = "Cliente") -> str:
    """Consulta a Gemini API usando la SDK oficial `google-genai`."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY no está definida en las variables de entorno.")
        return "Hola, estamos experimentando un problema de configuración temporal. Un ejecutivo se pondrá en contacto contigo a la brevedad."

    datos = obtener_datos_negocio()
    contexto = obtener_contexto_horario()

    texto_lower = user_text.lower()
    info_agenda = ""
    
    tz_chile = timezone(timedelta(hours=-3))
    hoy = datetime.now(tz_chile)
    
    if "mañana" in texto_lower:
        fecha_consulta = (hoy + timedelta(days=1)).strftime("%Y-%m-%d")
        info_agenda = obtener_bloques_ocupados(fecha_consulta)
    elif any(kw in texto_lower for kw in ["hoy", "agendar", "reunion", "cita", "hora"]):
        fecha_consulta = hoy.strftime("%Y-%m-%d")
        info_agenda = obtener_bloques_ocupados(fecha_consulta)

    prompt = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Reglas de atención:
{datos['reglas_atencion']}
Contacto de derivación humana: {datos['telefono_contacto']}.

Contexto operativo: [{contexto}]

Disponibilidad en Google Calendar (si aplica a la consulta):
{info_agenda if info_agenda else 'Sin consultas directas a la agenda en este turno.'}

Soluciones y servicios disponibles en base de datos / catálogo:
{datos['catalogo_texto']}

Mensaje del cliente ({nombre_cliente} - Teléfono: {telefono_cliente}): {user_text}

Instrucciones de respuesta:
1. Responde en tono profesional, claro y estructurado para WhatsApp.
2. Si el cliente solicita catálogo o listado de varios productos, detalla cada uno de forma clara en viñetas sin escatimar información.
3. Si el cliente solicita agendar una reunión o demo, utiliza la disponibilidad informada. Si hay un bloque disponible propónselo formalmente.
"""

    modelos_a_probar = ["gemini-2.5-flash", "gemini-1.5-flash"]

    try:
        client = genai.Client(api_key=gemini_key)
        
        for modelo in modelos_a_probar:
            try:
                response = client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=1200
                    )
                )
                if response and response.text:
                    respuesta = response.text.strip()
                    guardar_historial(telefono_cliente, "bot", respuesta)
                    return respuesta
            except Exception as e_mod:
                print(f"⚠️ Falló consulta con modelo {modelo}: {e_mod}")

    except Exception as e:
        print(f"❌ Error inicializando cliente Google GenAI: {e}")

    print("❌ Error: Ningún modelo de Gemini respondió con éxito.")
    return "Hola, un momento por favor. Estamos procesando tu consulta y un ejecutivo te contactará en breve."


# ------------------------------------------------------------------------------
# 4. Servidor Webhook FastAPI
# ------------------------------------------------------------------------------
app = FastAPI(title="Smoke Studios - WhatsApp Agent API")

class MensajeManualRequest(BaseModel):
    telefono: str
    mensaje: str

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Smoke Studios Bot"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge"), status_code=200, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.json()
    try:
        entries = body.get("entry", [])
        if entries:
            changes = entries[0].get("changes", [])
            if changes:
                value = changes[0].get("value", {})
                contacts = value.get("contacts", [])
                messages = value.get("messages", [])

                if messages:
                    msg = messages[0]
                    from_number = msg.get("from")
                    nombre = contacts[0].get("profile", {}).get("name", "Cliente") if contacts else "Cliente"

                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print(f"\n📩 [WhatsApp de {nombre} ({from_number})]: {text_body}")

                        # 1. Validar Rate Limiting y longitud
                        es_valido, msj_error = validar_mensaje_entrante(from_number, text_body)
                        if not es_valido:
                            send_whatsapp_message(from_number, msj_error)
                            return {"status": "rate_limited"}

                        # 2. Guardar en PostgreSQL local
                        guardar_historial(from_number, "cliente", text_body)

                        # 3. Evaluar intención de escalación
                        requiere_humano = detectar_solicitud_humana(text_body)

                        # 4. Sincronizar en tiempo real con Supabase (para Dashboard Next.js)
                        sincronizar_chat_supabase(
                            telefono=from_number,
                            cliente_nombre=nombre,
                            ultimo_mensaje=text_body,
                            requiere_humano=requiere_humano
                        )

                        # 5. Generar respuesta con IA y enviar
                        reply = ask_agent(text_body, from_number, nombre)
                        send_whatsapp_message(from_number, reply)
                        print(f"🤖 [Respuesta Enviada]: {reply}\n")

                        return {"status": "success"}

        return {"status": "ignored"}
    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/send-message")
async def enviar_mensaje_manual(data: MensajeManualRequest):
    try:
        # 1. Enviar el mensaje a través de Meta Cloud API
        send_whatsapp_message(data.telefono, data.mensaje)
        
        # 2. Registrar en la base de datos como enviado por el operador humano
        guardar_historial(data.telefono, "operador", data.mensaje)
        
        # 3. Sincronizar con Supabase para mantener la vista actualizada
        sincronizar_chat_supabase(
            telefono=data.telefono,
            cliente_nombre="Cliente",
            ultimo_mensaje=data.mensaje,
            requiere_humano=True
        )
        
        return {"status": "success", "message": "Mensaje enviado correctamente"}
    except Exception as e:
        print(f"❌ Error al enviar mensaje manual: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_whatsapp:app", host="0.0.0.0", port=8001, reload=True)