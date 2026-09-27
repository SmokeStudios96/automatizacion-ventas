import os
from datetime import datetime, timezone, timedelta
import requests
from fastapi import FastAPI, Request, Response
from database import SessionLocal, NegocioConfig, Producto, HistorialMensaje

# ------------------------------------------------------------------------------
# 1. Configuración desde Variables de Entorno de Render
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w")
WHATSAPP_TOKEN = os.environ.get(
    "WHATSAPP_TOKEN",
    "EAAeol1PvNZAIBSrfP62tK2YzT7UhaukOY6wlSSdewForp4QGWdr08KZCETq7G66ko94oCuAkNcJkmFVn5YZCR4htYu6snqSGSrnlOUo0idFZAZAR3Klq3VFtqmTxPlezU5fme6TZAGyjMh8rQObUjRcPLr5QXpZBiiekZCtrMLImSZCccV9fGLmmnaxdIotVtZAnVcZBzO3pJXKJmfFwzvkED4VIT78QL0i4NNm1fak111XrLRWR2wO8MqByEBz65TsmxFDv4QZAGPt9WM8amAy4YgrjegZDZD"
)
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1293789687158465")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "don_tito_ferreteria_secret_token")

def obtener_datos_negocio():
    """Carga la configuración del negocio y productos desde PostgreSQL en tiempo real."""
    db = SessionLocal()
    try:
        negocio = db.query(NegocioConfig).first()
        if not negocio:
            # Fallback por defecto si la BD estuviera vacía
            return {
                "nombre_negocio": "Ferretería Don Tito",
                "persona_ia": "Don Tito",
                "reglas_atencion": "1. Eres claro, preciso y directo.",
                "telefono_contacto": "+56939270181",
                "catalogo_texto": "- Bekron Estándar Sacos 25kg (SKU: ADH-019): $6.490 CLP | Stock: 95 un"
            }
        
        productos = db.query(Producto).filter(Producto.negocio_id == negocio.id).all()
        catalog_text = "\n".join([
            f"- {p.nombre} (SKU: {p.sku}): ${p.precio:,.0f} CLP | Stock: {p.stock} un | Categoría: {p.categoria}"
            for p in productos
        ]) if productos else "- No hay productos registrados."

        return {
            "nombre_negocio": negocio.nombre_negocio,
            "persona_ia": negocio.persona_ia,
            "reglas_atencion": negocio.reglas_atencion or "1. Sé amable y directo.",
            "telefono_contacto": negocio.telefono_contacto or "+56939270181",
            "catalogo_texto": catalog_text
        }
    except Exception as e:
        print(f"⚠️ Error conectando a PostgreSQL para obtener el negocio: {e}")
        return {
            "nombre_negocio": "Ferretería Don Tito",
            "persona_ia": "Don Tito",
            "reglas_atencion": "1. Sé amable y directo.",
            "telefono_contacto": "+56939270181",
            "catalogo_texto": "- Catálogo temporal no disponible."
        }
    finally:
        db.close()

def guardar_historial(telefono: str, remitente: str, mensaje: str):
    """Guarda el mensaje del cliente o del bot en la base de datos."""
    db = SessionLocal()
    try:
        nuevo_historial = HistorialMensaje(
            cliente_telefono=telefono,
            remitente=remitente,
            mensaje=mensaje
        )
        db.add(nuevo_historial)
        db.commit()
    except Exception as e:
        print(f"❌ Error guardando historial en PostgreSQL: {e}")
    finally:
        db.close()

def obtener_contexto_horario():
    """Calcula el contexto de fecha y hora para Chile (UTC-3)."""
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)
    
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")
    
    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0
    
    en_turno_manana = 9.0 <= hora_decimal < 13.0
    en_turno_tarde = 14.5 <= hora_decimal < 18.5
    
    esta_abierto = (not es_domingo) and (en_turno_manana or en_turno_tarde)
    estado = "ABIERTO (atención presencial)" if esta_abierto else "CERRADO (fuera de horario de atención)"
    
    return f"Momento actual: {dia_str} a las {hora_str} hrs. Estado del local: {estado}."

# ------------------------------------------------------------------------------
# 2. Funciones de Consulta a Gemini y Envío a WhatsApp
# ------------------------------------------------------------------------------
def send_whatsapp_message(recipient, text):
    """Envía el mensaje de respuesta al cliente vía WhatsApp."""
    token_actual = os.environ.get("WHATSAPP_TOKEN", WHATSAPP_TOKEN)
    phone_id_actual = os.environ.get("PHONE_NUMBER_ID", PHONE_NUMBER_ID)

    url = f"https://graph.facebook.com/v20.0/{phone_id_actual}/messages"
    headers = {
        "Authorization": f"Bearer {token_actual}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }

    response = requests.post(url, json=payload, headers=headers)
    print(f"📤 Estado del envío a Meta: {response.status_code}")
    if response.status_code != 200:
        print(f"❌ Detalles error Meta: {response.text}")

def ask_agent(user_text, telefono_cliente):
    """Consulta a Gemini 3.6 Flash utilizando la configuración dinámica del negocio en PostgreSQL."""
    gemini_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={gemini_key}"
    
    # Cargamos dinámicamente los datos del negocio desde la base de datos
    datos_negocio = obtener_datos_negocio()
    contexto = obtener_contexto_horario()

    prompt_instrucciones = f"""Eres {datos_negocio['persona_ia']}, asistente virtual de {datos_negocio['nombre_negocio']}.
Reglas de atención del negocio:
{datos_negocio['reglas_atencion']}
Nota adicional: Si debes derivar o entregar contacto humano, utiliza el número {datos_negocio['telefono_contacto']}.

Contexto horario actual: [{contexto}]

Catálogo de productos disponibles en base de datos:
{datos_negocio['catalogo_texto']}

Mensaje del cliente: {user_text}
"""

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt_instrucciones}]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            respuesta_ia = data["candidates"][0]["content"]["parts"][0]["text"]
            
            # Guardamos la respuesta del bot en el historial de PostgreSQL
            guardar_historial(telefono_cliente, "bot", respuesta_ia)
            return respuesta_ia
        else:
            print(f"❌ Error HTTP de Gemini ({response.status_code}): {response.text}")
            return "Lo siento compadre, ocurrió un problema al consultar el sistema."
    except Exception as e:
        print(f"❌ Excepción en llamada Gemini: {e}")
        return "Lo siento compadre, ocurrió un problema al consultar el sistema."

# ------------------------------------------------------------------------------
# 3. Servidor Web
# ------------------------------------------------------------------------------
app = FastAPI(title="API Automatización WhatsApp Agnóstica")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    verify_token_actual = os.environ.get("VERIFY_TOKEN", VERIFY_TOKEN)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token_actual:
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
                messages = value.get("messages", [])
                if messages:
                    msg = messages[0]
                    from_number = msg.get("from")
                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                        print(f"\n📩 [WHATSAPP de {from_number}]: {text_body}")

                        # Guardamos el mensaje entrante del cliente en PostgreSQL
                        guardar_historial(from_number, "cliente", text_body)

                        # Consultamos a la IA pasándole su número
                        reply = ask_agent(text_body, from_number)
                        print(f"🤖 [AGENTE]: {reply}\n")

                        send_whatsapp_message(from_number, reply)
                        return {"status": "success"}

        return {"status": "ignored"}
    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agent_whatsapp:app", host="0.0.0.0", port=8001, reload=True)