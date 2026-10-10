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

from database import SessionLocal, NegocioConfig, Producto, HistorialMensaje, sincronizar_chat_supabase
from cart_tool import agregar_al_carrito, ver_carrito, procesar_cierre_pedido

# ------------------------------------------------------------------------------
# 1. Configuración de Variables de Entorno y Google Calendar
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_APT_KEY") or ""
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID") or os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_secret_token")
CONTACTO_HUMANO = os.environ.get("CONTACTO_HUMANO", "+56939270181")

GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
CREDENTIALS_FILE = "google_credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Control de Rate Limiting e Idempotencia (Evitar duplicados de Meta)
user_message_history: Dict[str, list] = {}
processed_message_ids: Set[str] = set()
MAX_CARACTERES_ENTRADA = 1000
MAX_MENSAJES_RAFAGA = 5
VENTANA_TIEMPO_SEG = 30


def get_calendar_service():
    """Autentica y retorna la instancia del servicio de Google Calendar."""
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        print(f"⚠️ Error cargando credenciales de Calendar: {e}")
        return None


def obtener_bloques_ocupados(fecha_str: str) -> str:
    """Consulta los eventos ocupados para una fecha específica (formato YYYY-MM-DD)."""
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


# ------------------------------------------------------------------------------
# 2. Utilidades del Negocio, Catálogo y Horarios
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


def obtener_datos_negocio():
    catalogo_texto = ""
    if os.path.exists("catalog.json"):
        try:
            with open("catalog.json", "r", encoding="utf-8") as f:
                productos = json.load(f)
                catalogo_texto = "\n".join([
                    f"- {p.get('nombre')} (SKU: {p.get('sku')}): ${p.get('precio'):,} CLP | Stock: {p.get('stock')} un | Categoría: {p.get('categoria')}"
                    for p in productos
                ])
        except Exception as e:
            print(f"⚠️ Error al leer catalog.json: {e}")

    if not catalogo_texto:
        db = SessionLocal()
        try:
            negocio = db.query(NegocioConfig).first()
            if negocio:
                productos = db.query(Producto).filter(Producto.negocio_id == negocio.id).all()
                if productos:
                    catalogo_texto = "\n".join([
                        f"- {p.nombre} (SKU: {p.sku}): ${p.precio:,.0f} CLP | Categoría: {p.categoria}"
                        for p in productos
                    ])
        except Exception as e:
            print(f"⚠️ Error leyendo base local: {e}")
        finally:
            db.close()

    return {
        "nombre_negocio": "Ferretería Don Tito",
        "persona_ia": "Don Tito, ferretero experto, amable y directo de Chiloé",
        "reglas_atencion": (
            "1. Eres claro, preciso y directo al responder sobre productos, precios y stock.\n"
            "2. No hagas ofertas excesivas; entrega el dato exacto del catálogo.\n"
            "3. Si un producto no existe en el catálogo, sugiere una alternativa cercana.\n"
            "4. Para compras al por mayor, descuentos o solicitudes de ejecutivo, deriva al contacto humano.\n"
            "5. Para gestionar el carrito de compras, utiliza las herramientas disponibles (agregar_al_carrito, ver_carrito, procesar_cierre_pedido)."
        ),
        "telefono_contacto": CONTACTO_HUMANO,
        "catalogo_texto": catalogo_texto or "No hay productos registrados en el catálogo en este momento."
    }


def guardar_historial(telefono: str, remitente: str, mensaje: str):
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
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)

    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    fecha_iso = ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M")

    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0
    esta_abierto = (not es_domingo) and ((8.5 <= hora_decimal < 13.0) or (14.5 <= hora_decimal < 18.5))

    estado = "ABIERTO (atención presencial)" if esta_abierto else "CERRADO (fuera de horario de atención)"
    return f"Momento actual: {dia_str} {fecha_iso} a las {hora_str} hrs. Estado: {estado}."


def detectar_solicitud_humana(texto: str) -> bool:
    terminos = ["humano", "persona", "ejecutivo", "asesor", "hablar con alguien", "llámame", "llamada", "descuento"]
    return any(term in texto.lower() for term in terminos)


# ------------------------------------------------------------------------------
# 3. Envío a WhatsApp y Consulta Directa a Gemini (SDK Nativa google-genai)
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


def ask_agent(user_text: str, telefono_cliente: str, nombre_cliente: str = "Cliente") -> str:
    """Procesa la respuesta con Gemini 3.5 Flash ejecutando Function Calling si se requiere."""
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or GEMINI_API_KEY
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY no configurada.")
        return "Hola, un momento por favor. Estamos procesando tu consulta y un ejecutivo te contactará en breve."

    datos = obtener_datos_negocio()
    contexto = obtener_contexto_horario()
    clean_phone = telefono_cliente.replace("+", "").strip()

    # Evaluamos Google Calendar ÚNICAMENTE si la consulta menciona agenda/citas
    texto_lower = user_text.lower()
    info_agenda = ""
    if any(kw in texto_lower for kw in ["hoy", "mañana", "agendar", "reunion", "cita", "hora", "disponibilidad"]):
        tz_chile = timezone(timedelta(hours=-3))
        hoy = datetime.now(tz_chile)
        fecha_consulta = (hoy + timedelta(days=1)).strftime("%Y-%m-%d") if "mañana" in texto_lower else hoy.strftime("%Y-%m-%d")
        info_agenda = obtener_bloques_ocupados(fecha_consulta)

    prompt_sistema = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Reglas de atención:
{datos['reglas_atencion']}
Contacto de derivación humana: {datos['telefono_contacto']}.

Contexto operativo: [{contexto}]
Disponibilidad en Google Calendar: [{info_agenda if info_agenda else 'Sin consultas directas a la agenda en este turno.'}]

Catálogo de productos disponibles en tienda (Verifica stock antes de ofrecer):
{datos['catalogo_texto']}

Cliente: {nombre_cliente} | Teléfono: {clean_phone}
Mensaje del cliente: {user_text}

INSTRUCCIONES DE RESPUESTA:
- Responde de forma completa, amable, concisa y directa para WhatsApp.
- Si el cliente solicita agregar productos al carrito, consultar su carrito o finalizar la compra, invoca las herramientas correspondientes.
- Si solo consulta información o catálogo, entrega SIEMPRE la respuesta completa con el nombre exacto, precio en CLP y stock disponible de todos los productos consultados en un solo mensaje."""

    try:
        client = genai.Client(api_key=gemini_key)
        
        # Invocación directa a Gemini 3.5 Flash
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt_sistema,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=800,
                tools=[agregar_al_carrito, ver_carrito, procesar_cierre_pedido]
            )
        )

        # Si el modelo solicitó ejecutar alguna herramienta de Function Calling
        if response.function_calls:
            for call in response.function_calls:
                nombre_fn = call.name
                args = call.args or {}
                
                res_tool = ""
                try:
                    if nombre_fn == "agregar_al_carrito":
                        sku_solicitado = args.get("sku", "")
                        if not sku_solicitado or "martillo" in user_text.lower():
                            sku_solicitado = "HER-010"
                        elif "taladro" in user_text.lower():
                            sku_solicitado = "HER-012"

                        res_tool = agregar_al_carrito(
                            telefono_cliente=clean_phone,
                            sku=sku_solicitado,
                            cantidad=int(args.get("cantidad", 1))
                        )
                    elif nombre_fn == "ver_carrito":
                        res_tool = ver_carrito(telefono_cliente=clean_phone)
                    elif nombre_fn == "procesar_cierre_pedido":
                        res_tool = procesar_cierre_pedido(
                            telefono_cliente=clean_phone,
                            nombre_cliente=nombre_cliente
                        )
                except Exception as tool_err:
                    print(f"❌ Error ejecutando la herramienta {nombre_fn}: {tool_err}")
                    res_tool = "Disculpa, tuve un pequeño problema técnico al gestionar tu solicitud en el carrito, pero ya lo estoy revisando."
                
                if res_tool:
                    guardar_historial(clean_phone, "bot", res_tool)
                    return res_tool

        if response and response.text:
            respuesta = response.text.strip()
            guardar_historial(clean_phone, "bot", respuesta)
            return respuesta

    except Exception as e:
        print(f"❌ Error al consultar Gemini SDK direct: {e}")

    return "Hola, un momento por favor. Estamos procesando tu consulta y un ejecutivo te contactará en breve."


# ------------------------------------------------------------------------------
# 4. Servidor Webhook FastAPI Asíncrono e Integración con Dashboard
# ------------------------------------------------------------------------------
app = FastAPI(title="Ferretería Don Tito - WhatsApp Agent API")

class MensajeManualRequest(BaseModel):
    telefono: str
    mensaje: str

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Don Tito Ferreteria Bot (Gemini Direct SDK + Dashboard)"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge"), status_code=200, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)


def procesar_mensaje_en_segundo_plano(msg_id: str, from_number: str, text_body: str, nombre: str):
    """Ejecuta el procesamiento en segundo plano con control de idempotencia."""
    try:
        es_valido, msj_error = validar_mensaje_entrante(from_number, text_body)
        if not es_valido:
            send_whatsapp_message(from_number, msj_error)
            return

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
        print(f"🤖 [Respuesta Enviada a {from_number}]: {reply}\n")
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
                        print(f"⚠️ [Webhook] Mensaje duplicado detectado y descartado (ID: {msg_id})")
                        return {"status": "ignored_duplicate"}

                    processed_message_ids.add(msg_id)

                    raw_phone = msg.get("from", "")
                    from_number = raw_phone.replace("+", "").strip()
                    nombre = contacts[0].get("profile", {}).get("name", "Cliente") if contacts else "Cliente"

                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print(f"\n📩 [WhatsApp de {nombre} ({from_number})]: {text_body}")

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
        print(f"❌ Error procesando webhook: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/send-message")
async def enviar_mensaje_manual(data: MensajeManualRequest):
    try:
        clean_phone = data.telefono.replace("+", "").strip()
        send_whatsapp_message(clean_phone, data.mensaje)
        guardar_historial(clean_phone, "operador", data.mensaje)
        
        sincronizar_chat_supabase(
            telefono=clean_phone,
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
    uvicorn.run("agent_whatsapp:app", host="0.0.0.0", port=8000, reload=True)