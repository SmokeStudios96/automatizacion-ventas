import os
import time
import json
import requests
from typing import Dict, Tuple, Set
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Response, BackgroundTasks
from pydantic import BaseModel
from google import genai
from google.genai import types

from database import guardar_historial_seguro, sincronizar_chat_supabase
from calendar_dental_tool import get_available_slots, book_dental_appointment

# ------------------------------------------------------------------------------
# 1. Configuración de Variables de Entorno y Clínica
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APT_KEY") or ""
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "clinica_dental_sonrisas_secret_token")
CONTACTO_HUMANO = os.environ.get("CONTACTO_HUMANO", "+56939270181")

# Control de Rate Limiting e Idempotencia (Evitar duplicados de Meta)
user_message_history: Dict[str, list] = {}
processed_message_ids: Set[str] = set()
MAX_CARACTERES_ENTRADA = 1000
MAX_MENSAJES_RAFAGA = 5
VENTANA_TIEMPO_SEG = 30


# ------------------------------------------------------------------------------
# 2. Utilidades y Reglas del Negocio (Clínica Dental)
# ------------------------------------------------------------------------------
def validar_mensaje_entrante(telefono: str, texto_mensaje: str) -> Tuple[bool, str]:
    ahora = time.time()
    if len(texto_mensaje) > MAX_CARACTERES_ENTRADA:
        return False, "Tu mensaje es muy extenso. Por favor, envía una consulta más breve."
    if telefono not in user_message_history:
        user_message_history[telefono] = []
    user_message_history[telefono] = [t for t in user_message_history[telefono] if ahora - t < VENTANA_TIEMPO_SEG]
    if len(user_message_history[telefono]) >= MAX_MENSAJES_RAFAGA:
        return False, "Has enviado varios mensajes muy rápido. Por favor, aguarda unos segundos."
    user_message_history[telefono].append(ahora)
    return True, ""


def obtener_datos_clinica():
    return {
        "nombre_negocio": "Clínica Dental Sonrisas del Sur",
        "persona_ia": "Sofía, recepcionista virtual amable, empática y profesional de la clínica dental",
        "reglas_atencion": (
            "1. Eres clara, amable y orientada a la salud y comodidad de los pacientes.\n"
            "2. Informa siempre sobre nuestros 4 especialistas, sus especialidades y días/horarios de atención cuando pregunten:\n"
            "   - Dr. Roberto Soto: Odontología General (Lunes a Viernes, 09:00 a 17:00 hrs)\n"
            "   - Dra. Camila Valenzuela: Ortodoncia (Martes y Jueves, 10:00 a 18:00 hrs)\n"
            "   - Dr. Ignacio Morales: Periodoncia (Lunes, Miércoles y Viernes, 14:00 a 19:00 hrs)\n"
            "   - Dra. Valentina Paz: Odontopediatría (Lunes a Jueves, 09:00 a 14:00 hrs)\n"
            "3. La clínica cuenta con 2 boxes de atención simultánea. El sistema valida automáticamente la disponibilidad.\n"
            "4. Para agendar una cita, solicita obligatoriamente: Nombre completo del paciente, el profesional/especialidad deseada y la fecha/hora en formato ISO (ej: YYYY-MM-DDTHH:MM:SS).\n"
            "5. Si el paciente requiere urgencias complejas o hablar con la administración, derívalo al contacto humano."
        ),
        "telefono_contacto": CONTACTO_HUMANO,
    }


def guardar_historial(telefono: str, remitente: str, mensaje: str):
    guardar_historial_seguro(telefono, remitente, mensaje, agente="dental")


def obtener_contexto_horario():
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    fecha_iso = now_iso = ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M")
    return f"Momento actual: {dia_str} {fecha_iso} a las {hora_str} hrs."


def detectar_solicitud_humana(texto: str) -> bool:
    terminos = ["humano", "persona", "recepcionista", "secretaria", "urgencia", "dolor", "emergencia", "llámame"]
    return any(term in texto.lower() for term in terminos)


# ------------------------------------------------------------------------------
# 3. Envío a WhatsApp y Consulta Directa a Gemini
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient: str, text: str):
    token = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", WHATSAPP_PHONE_ID)

    if not token or not phone_id:
        print("❌ Error: WHATSAPP_TOKEN o WHATSAPP_PHONE_ID faltante.")
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

    try:
        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            print(f"❌ Error al enviar mensaje por Meta ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ Error enviando mensaje a WhatsApp: {e}")


def ask_agent(user_text: str, telefono_cliente: str, nombre_cliente: str = "Paciente") -> str:
    """Procesa la respuesta con Gemini 3.5 Flash ejecutando Function Calling para Google Calendar y Supabase."""
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY no configurada.")
        return "Hola, un momento por favor. Estamos procesando tu consulta en la clínica."

    datos = obtener_datos_clinica()
    contexto = obtener_contexto_horario()
    clean_phone = telefono_cliente.replace("+", "").strip()

    # Consultar calendario si hay intención de agendar o ver disponibilidad
    texto_lower = user_text.lower()
    info_agenda = ""
    if any(kw in texto_lower for kw in ["hoy", "mañana", "agendar", "cita", "hora", "disponibilidad", "turno", "reserva"]):
        tz_chile = timezone(timedelta(hours=-3))
        hoy = datetime.now(tz_chile)
        fecha_consulta = (hoy + timedelta(days=1)).strftime("%Y-%m-%d") if "mañana" in texto_lower else hoy.strftime("%Y-%m-%d")
        info_agenda = get_available_slots(fecha_consulta)

    prompt_sistema = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Reglas de atención:
{datos['reglas_atencion']}
Contacto humano de apoyo: {datos['telefono_contacto']}.

Contexto operativo: [{contexto}]
Disponibilidad actual en Google Calendar: [{info_agenda if info_agenda else 'Sin consultas directas a la agenda en este mensaje.'}]

Paciente: {nombre_cliente} | Teléfono: {clean_phone}
Mensaje del paciente: {user_text}

INSTRUCCIONES DE RESPUESTA:
- Responde de forma cálida, profesional y concisa para WhatsApp.
- Si el paciente quiere consultar bloques disponibles o agendar una hora con alguno de los especialistas, utiliza las herramientas correspondientes (get_available_slots o book_dental_appointment).
- Asegúrate de pedir los datos faltantes al paciente de forma amable antes de intentar agendar."""

    try:
        client = genai.Client(api_key=gemini_key)
        
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt_sistema,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=800,
                tools=[get_available_slots, book_dental_appointment]
            )
        )

        if response.function_calls:
            for call in response.function_calls:
                nombre_fn = call.name
                args = call.args or {}
                
                res_tool = ""
                try:
                    if nombre_fn == "get_available_slots":
                        fecha_arg = args.get("date_str", datetime.now().strftime("%Y-%m-%d"))
                        res_tool = get_available_slots(fecha_str=fecha_arg)
                    elif nombre_fn == "book_dental_appointment":
                        res_tool = book_dental_appointment(
                            nombre_paciente=args.get("nombre_paciente", nombre_cliente),
                            profesional_solicitado=args.get("profesional_solicitado", "Roberto Soto"),
                            fecha_hora_inicio=args.get("fecha_hora_inicio", ""),
                            telefono_paciente=clean_phone
                        )
                except Exception as tool_err:
                    print(f"❌ Error ejecutando la herramienta {nombre_fn}: {tool_err}")
                    res_tool = "Disculpa, tuve un inconveniente técnico al conectar con el sistema de citas, pero ya lo reviso."
                
                if res_tool:
                    guardar_historial(clean_phone, "bot", res_tool)
                    return res_tool

        if response and response.text:
            respuesta = response.text.strip()
            guardar_historial(clean_phone, "bot", respuesta)
            return respuesta

    except Exception as e:
        print(f"❌ Error al consultar Gemini SDK direct: {e}")

    return "Hola, un momento por favor. Estamos procesando tu solicitud en la clínica."


# ------------------------------------------------------------------------------
# 4. Servidor Webhook FastAPI Asíncrono
# ------------------------------------------------------------------------------
app = FastAPI(title="Clínica Dental Sonrisas del Sur - WhatsApp Agent API")

class MensajeManualRequest(BaseModel):
    telefono: str
    mensaje: str

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Clinica Dental Bot (Gemini Direct SDK + Calendar + Supabase)"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge"), status_code=200, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)


def procesar_mensaje_en_segundo_plano(msg_id: str, from_number: str, text_body: str, nombre: str):
    try:
        es_valido, msj_error = validar_mensaje_entrante(from_number, text_body)
        if not es_valido:
            send_whatsapp_message(from_number, msj_error)
            return

        guardar_historial(from_number, "cliente", text_body)
        requiere_humano = detectar_solicitud_humana(text_body)

        try:
            sincronizar_chat_supabase(
                telefono=from_number,
                cliente_nombre=nombre,
                ultimo_mensaje=text_body,
                requiere_humano=requiere_humano,
                agente="dental"
            )
        except Exception as e:
            print(f"⚠️ Supabase sync falló suavemente: {e}")

        reply = ask_agent(text_body, from_number, nombre)
        send_whatsapp_message(from_number, reply)
        print(f"🤖 [Respuesta Clínica Enviada a {from_number}]: {reply}\n")
    except Exception as e:
        print(f"❌ Error en segundo plano: {e}")
    finally:
        if len(processed_message_ids) > 500:
            processed_message_ids.clear()


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
                    nombre = contacts[0].get("profile", {}).get("name", "Paciente") if contacts else "Paciente"

                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print(f"\n📩 [WhatsApp Clínico de {nombre} ({from_number})]: {text_body}")

                        background_tasks.add_task(
                            procesar_mensaje_en_segundo_plano,
                            msg_id,
                            from_number,
                            text_body,
                            nombre
                        )
                        return {"status": "processing"}

        return {"status": "ignored"}
    except Exception as e:
        print(f"❌ Error procesando webhook clínico: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/send-message")
async def enviar_mensaje_manual(data: MensajeManualRequest):
    try:
        clean_phone = data.telefono.replace("+", "").strip()
        send_whatsapp_message(clean_phone, data.mensaje)
        guardar_historial(clean_phone, "operador", data.mensaje)
        
        try:
            sincronizar_chat_supabase(
                telefono=clean_phone,
                cliente_nombre="Paciente",
                ultimo_mensaje=data.mensaje,
                requiere_humano=True,
                agente="dental"
            )
        except Exception:
            pass

        return {"status": "success", "message": "Mensaje enviado correctamente"}
    except Exception as e:
        print(f"❌ Error al enviar mensaje manual: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_dental:app", host="0.0.0.0", port=8000, reload=True)