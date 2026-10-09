import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

from agno.agent import Agent
from agno.models.google import Gemini

# Importar las herramientas del carrito conectadas a Supabase
from cart_tool import agregar_al_carrito, ver_carrito, procesar_cierre_pedido

# ------------------------------------------------------------------------------
# 1. Configuración de API Key de Gemini
# ------------------------------------------------------------------------------
API_KEY_GEMINI = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if API_KEY_GEMINI:
    os.environ["GEMINI_API_KEY"] = API_KEY_GEMINI


def obtener_contexto_horario() -> str:
    """Calcula el horario de atención comercial en Chiloé (UTC-3)."""
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)

    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")

    # Horario Ferretería Don Tito: Lunes a Sábado de 08:30 a 19:00 hrs
    es_domingo = ahora.weekday() == 6
    hora_decimal = ahora.hour + ahora.minute / 60.0
    en_horario = not es_domingo and (8.5 <= hora_decimal < 19.0)

    estado = (
        "ABIERTO (atención presencial y despacho activo)"
        if en_horario
        else "CERRADO (fuera de horario comercial, atención de consultas activa)"
    )

    return f"Momento actual: {dia_str} a las {hora_str} hrs (Chile). Estado del local: {estado}."


# ------------------------------------------------------------------------------
# 2. Inicialización del Agente Don Tito (Ferretería Don Tito)
# ------------------------------------------------------------------------------
don_tito_agent = Agent(
    model=Gemini(
        id="gemini-2.5-flash",
        api_key=API_KEY_GEMINI
    ),
    description="Eres Don Tito, un ferretero experto, amable y directo de Chiloé.",
    instructions=[
        "Eres Don Tito, dueño y ferretero de 'Ferretería Don Tito' en Chiloé.",
        "Responde con cercanía, amabilidad y modismos suaves del sur de Chile (ej. 'ya pues', 'estimado', 'mire').",
        "Eres claro, preciso y directo al responder sobre productos, precios y stock.",
        "CUANDO EL CLIENTE PIDA AGREGAR PRODUCTOS:",
        "- Usa la herramienta 'agregar_al_carrito' pasando el SKU del producto y la cantidad requerida.",
        "CUANDO EL CLIENTE PREGUNTE POR SU COMPRA O TOTAL:",
        "- Usa la herramienta 'ver_carrito' para detallar el contenido actual del carrito.",
        "CUANDO EL CLIENTE CONFIRME QUE DESEA FINALIZAR O PAGAR:",
        "- Usa la herramienta 'procesar_cierre_pedido' para generar el registro final y limpiar el carrito.",
        "REGLA DE ORO: Entrega precios exactos en pesos chilenos ($ CLP) y sé breve y útil para WhatsApp."
    ],
    tools=[agregar_al_carrito, ver_carrito, procesar_cierre_pedido],
    markdown=False
)


if __name__ == "__main__":
    contexto = obtener_contexto_horario()
    print(f"--- Contexto inyectado: {contexto} ---\n")

    prompt_prueba = (
        f"[{contexto}] Hola Don Tito, necesito saber si tiene martillo galponero y si me puede agregar 1 al carrito por favor."
    )
    
    print("Simulando respuesta de Don Tito con herramientas de carrito...\n")
    don_tito_agent.print_response(prompt_prueba)