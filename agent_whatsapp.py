import os
from datetime import datetime, timezone, timedelta
import requests
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from database import SessionLocal, NegocioConfig, Producto, HistorialMensaje, sincronizar_chat_supabase

# ------------------------------------------------------------------------------
# 1. Configuración de Variables de Entorno
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w"
)
WHATSAPP_TOKEN = os.environ.get(
    "WHATSAPP_TOKEN",
    "EAAeol1PvNZAIBSrfP62tK2YzT7UhaukOY6wlSSdewForp4QGWdr08KZCETq7G66ko94oCuAkNcJkmFVn5YZCR4htYu6snqSGSrnlOUo0idFZAZAR3Klq3VFtqmTxPlezU5fme6TZAGyjMh8rQObUjRcPLr5QXpZBiiekZCtrMLImSZCccV9fGLmmnaxdIotVtZAnVcZBzO3pJXKJmfFwzvkED4VIT78QL0i4NNm1fak111XrLRWR2wO8MqByEBz65TsmxFDv4QZAGPt9WM8amAy4YgrjegZDZD"
)
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_secret_token")
CONTACTO_HUMANO = os.environ.get("CONTACTO_HUMANO", "+56939270181")


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
            "3. Si el cliente solicita cotización a medida, descuento o hablar con una persona, deriva al contacto humano."
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
    hora_str = ahora.strftime("%H:%M")

    es_dia_laboral = ahora.weekday() < 5
    hora_decimal = ahora.hour + ahora.minute / 60.0
    esta_abierto = es_dia_laboral and (9.0 <= hora_decimal < 18.5)

    estado = "HORARIO COMERCIAL ACTIVO" if esta_abierto else "FUERA DE HORARIO COMERCIAL (Atención 24/7)"
    return f"Momento actual: {dia_str} a las {hora_str} hrs. Estado: {estado}."


def detectar_solicitud_humana(texto: str) -> bool:
    """Verifica si el usuario solicitó explícitamente a un agente humano."""
    terminos = [
        "humano", "persona", "ejecutivo", "asesor", "hablar con alguien",
        "llámame", "llamada", "reunión", "descuento", "cotización personalizada"
    ]
    t = texto.lower()
    return any(term in t for term in terminos)


# ------------------------------------------------------------------------------
# 2. Envío a WhatsApp y Consulta a Gemini
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient, text):
    """Envía el mensaje de texto al usuario por WhatsApp Cloud API."""
    token = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)

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
    """Consulta a Gemini 2.5 Flash con el contexto comercial de Smoke Studios."""
    gemini_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"

    datos = obtener_datos_negocio()
    contexto = obtener_contexto_horario()

    prompt = f"""Eres {datos['persona_ia']} de {datos['nombre_negocio']}.
Reglas de atención:
{datos['reglas_atencion']}
Contacto de derivación humana: {datos['telefono_contacto']}.

Contexto operativo: [{contexto}]
Soluciones y servicios:
{datos['catalogo_texto']}

Mensaje del cliente ({nombre_cliente}): {user_text}
Responde en tono profesional, claro y conciso para WhatsApp:
"""

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()
            respuesta = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            guardar_historial(telefono_cliente, "bot", respuesta)
            return respuesta
        else:
            print(f"❌ Error de Gemini API ({r.status_code}): {r.text}")
            return "Hola, un momento por favor. Estamos procesando tu consulta y un ejecutivo te contactará en breve."
    except Exception as e:
        print(f"❌ Excepción al conectar con Gemini: {e}")
        return "Hola, gracias por escribir a Smoke Studios. Registramos tu mensaje y nos pondremos en contacto contigo pronto."


# ------------------------------------------------------------------------------
# 3. Servidor Webhook FastAPI
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

                        # 1. Guardar en PostgreSQL local
                        guardar_historial(from_number, "cliente", text_body)

                        # 2. Evaluar intención de escalación
                        requiere_humano = detectar_solicitud_humana(text_body)

                        # 3. Sincronizar en tiempo real con Supabase (para Dashboard Next.js)
                        sincronizar_chat_supabase(
                            telefono=from_number,
                            cliente_nombre=nombre,
                            ultimo_mensaje=text_body,
                            requiere_humano=requiere_humano
                        )

                        # 4. Generar respuesta con IA y enviar
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