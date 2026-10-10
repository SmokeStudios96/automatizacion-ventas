import os
import time
import json
import requests
from typing import Dict, Tuple, Set
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Response, BackgroundTasks
from pydantic import BaseModel
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from google import genai
from google.genai import types

from database import SessionLocal, sincronizar_chat_supabase
from calendar_estetica_tool import book_estetica_appointment, get_available_slots_estetica

# ------------------------------------------------------------------------------
# 1. Configuración de Variables de Entorno y Google Calendar
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APT_KEY") or ""
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ona_pmu_secret_token")
CONTACTO_HUMANO = os.environ.get("CONTACTO_HUMANO", "+56939270181")

GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID_ESTETICA")
CREDENTIALS_FILE = "google_credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

user_message_history: Dict[str, list] = {}
processed_message_ids: Set[str] = set()
MAX_CARACTERES_ENTRADA = 1000
MAX_MENSAJES_RAFAGA = 5
VENTANA_TIEMPO_SEG = 30


def obtener_bloques_ocupados(fecha_str: str) -> str:
    return get_available_slots_estetica(fecha_str)


# ------------------------------------------------------------------------------
# 2. Datos del Negocio (Estética y Academia PMU - Ona Songailaite)
# ------------------------------------------------------------------------------
def obtener_datos_negocio():
    return {
        "nombre_negocio": "Academia y Estética PMU - Ona Songailaite",
        "persona_ia": "Asistente virtual especialista en atención al cliente de Ona Songailaite",
        "reglas_atencion": (
            "1. Eres cálida, profesional y experta en belleza, micropigmentación (PMU), microblading y formaciones profesionales.\n"
            "2. Informa sobre los servicios estéticos (microblading, micropigmentación de labios/cejas) y sobre los cursos especializados (ej. Guía de Pigmentología y Colorimetría, formaciones presenciales).\n"
            "3. Si el cliente quiere agendar una evaluación estética o inscribirse a un curso, consulta su disponibilidad y ayúdale a reservar utilizando la herramienta de agendamiento.\n"
            "4. Deriva al contacto humano ante dudas complejas de salud o requerimientos especiales."
        ),
        "telefono_contacto": CONTACTO_HUMANO,
        "servicios_cursos": (
            "- Microblading y Micropigmentación Facial (Cejas, Labios, Ojos)\n"
            "- Curso / Guía de Pigmentología y Colorimetría para Micropigmentación (Hotmart)\n"
            "- Asesorías y Formaciones Profesionales Avanzadas para artistas del rubro"
        )
    }


def guardar_historial(telefono: str, remitente: str, mensaje: str):
    db = SessionLocal()
    try:
        from database import HistorialMensaje
        nuevo = HistorialMensaje(cliente_telefono=telefono, remitente=remitente, mensaje=mensaje)
        db.add(nuevo)
        db.commit()
    except Exception as e:
        print(f"❌ Error guardando historial: {e}")
    finally:
        db.close()


def detectar_solicitud_humana(texto: str) -> bool:
    terminos = ["humano", "persona", "asesor", "hablar con alguien", "profe", "ona", "atención personalizada"]
    return any(term in texto.lower() for term in terminos)


# ------------------------------------------------------------------------------
# 3. Integración con Gemini SDK
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient: str, text: str):
    token = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", WHATSAPP_PHONE_ID)

    if not token or not phone_id:
        return

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient, "type": "text", "text": {"body": text}}

    try:
        requests.post(url, json=payload, headers=headers)
    except Exception as e:
        print(f"❌ Error enviando mensaje a WhatsApp: {e}")


def ask_agent(user_text: str, telefono_cliente: str, nombre_cliente: str = "Cliente") -> str:
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY
    if not gemini_key:
        return "Hola, un momento por favor. En breve te atendemos."

    datos = obtener_datos_negocio()
    clean_phone = telefono_cliente.replace("+", "").strip()

    texto_lower = user_text.lower()
    info_agenda = ""
    if any(kw in texto_lower for kw in ["hoy", "mañana", "agendar", "cita", "curso", "cupo", "hora", "disponibilidad"]):
        tz_chile = timezone(timedelta(hours=-3))
        hoy = datetime.now(tz_chile)
        fecha_consulta = (hoy + timedelta(days=1)).strftime("%Y-%m-%d") if "mañana" in texto_lower else hoy.strftime("%Y-%m-%d")
        info_agenda = obtener_bloques_ocupados(fecha_consulta)

    prompt_sistema = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Reglas de atención:
{datos['reglas_atencion']}

Servicios y Capacitaciones Principales:
{datos['servicios_cursos']}

Disponibilidad en Google Calendar: [{info_agenda if info_agenda else 'Sin consulta de agenda directa.'}]

Cliente: {nombre_cliente} | Teléfono: {clean_phone}
Mensaje del cliente: {user_text}

INSTRUCCIONES DE RESPUESTA:
- Responde de forma elegante, cercana, clara y orientada a la conversión para WhatsApp.
- Si muestra interés en un curso o procedimiento, explícale los detalles principales e invítale a asegurar su cupo o cita."""

    try:
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt_sistema,
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=800)
        )

        if response and response.text:
            respuesta = response.text.strip()
            guardar_historial(clean_phone, "bot", respuesta)
            return respuesta
    except Exception as e:
        print(f"❌ Error en Gemini: {e}")

    return "Hola, gracias por escribirnos. Un asesor se pondrá en contacto contigo en breve."


# ------------------------------------------------------------------------------
# 4. Servidor FastAPI Webhook
# ------------------------------------------------------------------------------
app = FastAPI(title="Estética PMU - Ona Songailaite Bot API")

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Ona Songailaite PMU Bot"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge"), status_code=200, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)


def procesar_mensaje_en_segundo_plano(msg_id: str, from_number: str, text_body: str, nombre: str):
    try:
        guardar_historial(from_number, "cliente", text_body)
        requiere_humano = detectar_solicitud_humana(text_body)

        sincronizar_chat_supabase(
            telefono=from_number,
            cliente_nombre=nombre,
            ultimo_mensaje=text_body,
            requiere_humano=requiere_humano
        )

        reply = ask_agent(text_body, from_number, nombre)
        send_whatsapp_message(from_number, reply)
    except Exception as e:
        print(f"❌ Error en segundo plano: {e}")


@app.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
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
                    msg_id = msg.get("id", "")
                    if msg_id in processed_message_ids:
                        return {"status": "ignored_duplicate"}
                    processed_message_ids.add(msg_id)

                    raw_phone = msg.get("from", "")
                    from_number = raw_phone.replace("+", "").strip()
                    nombre = contacts[0].get("profile", {}).get("name", "Cliente") if contacts else "Cliente"

                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        background_tasks.add_task(procesar_mensaje_en_segundo_plano, msg_id, from_number, text_body, nombre)
                        return {"status": "processing"}
        return {"status": "ignored"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_estetica:app", host="0.0.0.0", port=8000, reload=True)