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

from database import guardar_historial_seguro, sincronizar_chat_supabase, SessionLocal
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


def obtener_historial_chat(clean_phone: str) -> str:
    """Recupera los últimos 6 mensajes del historial desde PostgreSQL para dar contexto."""
    try:
        db = SessionLocal()
        sql_hist = """
            SELECT remitente, mensaje 
            FROM historial_chats 
            WHERE telefono = :tel AND agente = 'estetica'
            ORDER BY fecha_hora DESC LIMIT 6;
        """
        rows = db.execute(sql_hist, {"tel": clean_phone}).fetchall()
        db.close()
        
        if rows:
            mensajes_previos = []
            for r in reversed(rows):
                rol = "Cliente" if r.remitente == "cliente" else "Asistente"
                mensajes_previos.append(f"{rol}: {r.mensaje}")
            return "\n".join(mensajes_previos)
    except Exception as err_hist:
        print(f"⚠️ No se pudo cargar el historial: {err_hist}")
    return ""


# ------------------------------------------------------------------------------
# 2. Datos del Negocio (Estética y Academia PMU - Ona Songailaite)
# ------------------------------------------------------------------------------
def obtener_datos_negocio():
    return {
        "nombre_negocio": "Academia y Estética PMU - Ona Songailaite",
        "persona_ia": "Asistente virtual especialista en atención al cliente de Ona Songailaite",
        "reglas_atencion": (
            "1. Eres cálida, profesional, directa y experta en belleza, micropigmentación (PMU), microblading y formaciones profesionales.\n"
            "2. IMPORTANTE PARA NATURALIDAD: Revisa el HISTORIAL. Saluda una sola vez al inicio de la interacción. Si el cliente está respondiendo una pregunta de seguimiento (ej: 'Sí, primera vez', 'A las 10 hrs', 'Lunes'), NO VUELVAS A SALUDAR NI A DAR LA BIENVENIDA. Responde de forma fluida y continua.\n"
            "3. Informa sobre los servicios estéticos y sus valores exactos cuando el cliente pregunte.\n"
            "4. Si en el historial o mensaje actual el cliente indica servicio, fecha y hora (ej: Microblading, Lunes a las 10:00 hrs), UTILIZA DE INMEDIATO la herramienta 'book_estetica_appointment'.\n"
            "5. Deriva al contacto humano ante dudas complejas de salud o requerimientos especiales."
        ),
        "telefono_contacto": CONTACTO_HUMANO,
        "servicios_cursos": (
            "PROCEDIMIENTOS DE ESTÉTICA Y PMU:\n"
            "- Microblading de Cejas: $150.000 (Duración: 2 hrs)\n"
            "- Micropigmentación de Labios: $160.000 (Duración: 2.5 hrs)\n"
            "- Efecto Polvo Cejas (Powder Brows): $140.000 (Duración: 2 hrs)\n"
            "- Repaso / Retoque de Cejas: $50.000 (Duración: 1.5 hrs)\n\n"
            "FORMACIONES Y ACADEMIA PMU:\n"
            "- Guía Digital de Pigmentología y Colorimetría para PMU (Disponible en Hotmart)\n"
            "- Cursos Presenciales y Masterclasses para artistas del rubro"
        )
    }


def guardar_historial(telefono: str, remitente: str, mensaje: str):
    guardar_historial_seguro(telefono, remitente, mensaje, agente="estetica")


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

    # Cargar historial de conversación
    historial_texto = obtener_historial_chat(clean_phone)

    tz_chile = timezone(timedelta(hours=-3))
    ahora_chile = datetime.now(tz_chile)
    fecha_actual_str = ahora_chile.strftime("%Y-%m-%d %H:%M:%S")

    texto_lower = user_text.lower()
    info_agenda = ""
    if any(kw in texto_lower for kw in ["hoy", "mañana", "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "agendar", "cita", "curso", "cupo", "hora", "disponibilidad"]):
        fecha_consulta = (ahora_chile + timedelta(days=1)).strftime("%Y-%m-%d") if "mañana" in texto_lower else ahora_chile.strftime("%Y-%m-%d")
        info_agenda = obtener_bloques_ocupados(fecha_consulta)

    prompt_sistema = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Fecha y Hora Actual en Chile: {fecha_actual_str}

Reglas de atención:
{datos['reglas_atencion']}

Servicios, Precios y Capacitaciones Principales:
{datos['servicios_cursos']}

Disponibilidad en Google Calendar: [{info_agenda if info_agenda else 'Sin consulta de agenda directa.'}]

HISTORIAL DE LA CONVERSACIÓN RECIENTE CON ESTE CLIENTE:
{historial_texto if historial_texto else "Sin mensajes previos registrados."}

DATOS DEL CLIENTE ACTUAL:
Nombre: {nombre_cliente} | Teléfono: {clean_phone}
Último mensaje recibido: {user_text}

INSTRUCCIONES DE RESPUESTA Y ACCIÓN:
- Revisa el HISTORIAL para mantener la continuidad de la charla. No olvides lo que el cliente ya te dijo.
- Si en el historial o en el mensaje actual el cliente ya definió el servicio (ej: Microblading de Cejas) y la fecha/hora, EJECUTA DE INMEDIATO 'book_estetica_appointment'.
- Si solo consulta disponibilidades, usa 'get_available_slots_estetica'.
- Responde de forma cercana, natural y orientada a la conversión en WhatsApp."""

    try:
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt_sistema,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1500,
                tools=[get_available_slots_estetica, book_estetica_appointment]
            )
        )

        if response.function_calls:
            for call in response.function_calls:
                nombre_fn = call.name
                args = call.args or {}
                
                res_tool = ""
                try:
                    if nombre_fn == "get_available_slots_estetica":
                        fecha_arg = args.get("fecha_str", ahora_chile.strftime("%Y-%m-%d"))
                        res_tool = get_available_slots_estetica(date_str=fecha_arg)
                    elif nombre_fn == "book_estetica_appointment":
                        res_tool = book_estetica_appointment(
                            nombre_cliente=args.get("nombre_cliente", nombre_cliente),
                            servicio_solicitado=args.get("servicio_solicitado", "Microblading"),
                            fecha_hora_inicio=args.get("fecha_hora_inicio", ""),
                            telefono_cliente=clean_phone
                        )
                except Exception as tool_err:
                    print(f"❌ Error ejecutando la herramienta {nombre_fn}: {tool_err}")
                    res_tool = "Disculpa, tuve un inconveniente técnico al agendar en la agenda, pero ya lo revisamos."
                
                if res_tool:
                    guardar_historial(clean_phone, "bot", res_tool)
                    return res_tool

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

        try:
            sincronizar_chat_supabase(
                telefono=from_number,
                cliente_nombre=nombre,
                ultimo_mensaje=text_body,
                requiere_humano=requiere_humano,
                agente="estetica"
            )
        except Exception as e:
            print(f"⚠️ Supabase sync falló suavemente: {e}")

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