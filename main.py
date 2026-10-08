import os
from datetime import datetime, timezone, timedelta
from agno.agent import Agent
from agno.models.google import Gemini

# ------------------------------------------------------------------------------
# 1. Configuración de API Key (Cargar preferentemente vía .env)
# ------------------------------------------------------------------------------
os.environ["GEMINI_API_KEY"] = os.getenv(
    "GEMINI_API_KEY", "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w"
)

# Catálogo oficial de soluciones digitales de Smoke Studios
CATALOGO_SERVICIOS = """
1. DESARROLLO WEB & PLATAFORMAS A MEDIDA:
   - Sitios corporativos, landing pages de alto impacto y aplicaciones SaaS.
   - Stack tecnológico: Next.js 15, React 19, Tailwind CSS, TypeScript y despliegues en Vercel.
   - Enfoque: Velocidad de carga ultrarrápida, diseño responsivo premium y optimización SEO técnico.

2. AGENTES DE IA & AUTOMATIZACIÓN DE ATENCIÓN:
   - Asistentes virtuales para WhatsApp Business API con disponibilidad 24/7.
   - Respuestas inteligentes con contexto de negocio, bases de datos en tiempo real y catálogos.
   - Detección de intención comercial y derivación automática a ejecutivos humanos.

3. AUTOMATIZACIÓN DE FLUJOS & INTEGRACIONES (N8N / MAKE / WEBHOOKS):
   - Conexión de WhatsApp con CRMs (HubSpot, Notion, Supabase, Google Sheets).
   - Generación de cotizaciones automáticas, alertas de inventario y recordatorios.
   - Reducción drástica de costos operativos y horas manuales repetitivas.

4. PORTALES DE GESTIÓN & DASHBOARDS EN TIEMPO REAL:
   - Paneles privados en Next.js con Supabase Auth y sincronización Realtime.
   - Monitoreo en vivo de ventas, leads calificados y toma de control manual de chats.
"""

NUMERO_ESCALACION_HUMANA = "+56939270181"


def obtener_contexto_horario() -> str:
    """Calcula el horario comercial en Chile (UTC-3)."""
    tz_chile = timezone(timedelta(hours=-3))
    ahora = datetime.now(tz_chile)

    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_str = dias_semana[ahora.weekday()]
    hora_str = ahora.strftime("%H:%M")

    # Horario de oficina Smoke Studios: Lunes a Viernes 09:00 a 18:30 hrs
    es_dia_laboral = ahora.weekday() < 5
    hora_decimal = ahora.hour + ahora.minute / 60.0
    en_horario = es_dia_laboral and (9.0 <= hora_decimal < 18.5)

    estado = (
        "ABIERTO (Horario comercial activo, ejecutivos disponibles)"
        if en_horario
        else "CERRADO (Fuera de horario comercial, atención automática 24/7 activa)"
    )

    return f"Momento actual: {dia_str} {hora_str} hrs (Chile). Estado: {estado}."


# ------------------------------------------------------------------------------
# 2. Inicialización del Agente Comercial con Agno
# ------------------------------------------------------------------------------
smoke_commercial_agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    description="Eres el Ejecutivo Comercial Virtual de Smoke Studios.",
    instructions=[
        "Eres un asesor comercial experto, proactivo, transparente, educado y directo.",
        "Tu objetivo es explicar los servicios de desarrollo web, agentes de IA, automatizaciones y dashboards.",
        "Sé conciso y claro en tus mensajes. WhatsApp requiere respuestas dinámicas, directas y fáciles de leer en el teléfono.",
        f"Catálogo de soluciones de Smoke Studios:\n{CATALOGO_SERVICIOS}",
        "CRITERIOS DE DERIVACIÓN HUMANA (CRÍTICO):",
        "- Si el cliente solicita hablar con una persona/ejecutivo, pide una cotización personalizada a medida, solicita descuentos por volumen o agendar una reunión comercial:",
        f"  1. Acepta con total cordialidad e indícale que dejas la conversación transferida de inmediato con nuestro equipo humano al {NUMERO_ESCALACION_HUMANA}.",
        "- Si el cliente solo tiene dudas sobre tecnologías, funcionalidades o servicios, responde directamente.",
        "REGLA DE HORARIO:",
        "- Si el contexto indica 'CERRADO' y el cliente pide hablar con un ejecutivo, explícale que su solicitud quedó registrada con máxima prioridad y que el equipo se comunicará a primera hora hábil."
    ],
    markdown=False,
)

if __name__ == "__main__":
    contexto = obtener_contexto_horario()
    print(f"--- Contexto inyectado: {contexto} ---\n")

    prompt_prueba = (
        f"[{contexto}] Hola, me interesa saber si pueden crear un agente de WhatsApp con un Dashboard "
        f"en Next.js y Supabase para mi negocio, y cómo puedo agendar una llamada con un ejecutivo."
    )
    smoke_commercial_agent.print_response(prompt_prueba)