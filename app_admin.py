import os
import streamlit as st
import pandas as pd
from agno.agent import Agent
from agno.models.google import Gemini
from database import SessionLocal, Producto, NegocioConfig

st.set_page_config(page_title="Panel de Gestión & Asistente IA", page_icon="🤖", layout="wide")

st.title("🛠️ Panel de Gestión & Asistente IA")

# 1. Inicializar estado de sesión para el login y el historial de chat
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.negocio_id = None
    st.session_state.nombre_negocio = None

if "mensajes_chat" not in st.session_state:
    st.session_state.mensajes_chat = []

db = SessionLocal()

# 2. Pantalla de Login si no ha iniciado sesión
if not st.session_state.autenticado:
    st.subheader("🔐 Acceso al Panel de Gestión")
    
    usuario_ingresado = st.text_input("Usuario")
    password_ingresada = st.text_input("Contraseña", type="password")
    
    if st.button("Ingresar"):
        negocio = db.query(NegocioConfig).filter(
            NegocioConfig.usuario == usuario_ingresado,
            NegocioConfig.password == password_ingresada
        ).first()
        
        if negocio:
            st.session_state.autenticado = True
            st.session_state.negocio_id = negocio.id
            st.session_state.nombre_negocio = negocio.nombre_negocio
            # Cargar mensaje inicial de bienvenida en el chat
            st.session_state.mensajes_chat = [
                {"role": "assistant", "content": f"¡Hola! Soy tu **Ingeniero de Soporte Técnico del SaaS**. Estoy aquí para ayudarte a resolver cualquier inconveniente con tu automatización de ventas, problemas de conexión en WhatsApp/Meta o dudas sobre **{negocio.nombre_negocio}**. ¿En qué te puedo colaborar hoy?"}
            ]
            st.success(f"¡Bienvenido, {negocio.nombre_negocio}!")
            db.close()
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos")
    db.close()

else:
    # 3. Menú Lateral de Navegación (Gestión de Inventario primero)
    st.sidebar.markdown(f"### 🏢 **{st.session_state.nombre_negocio}**")
    
    opcion_menu = st.sidebar.radio(
        "Selecciona una opción:",
        ["📦 Gestión de Inventario", "💬 Soporte Técnico del Sistema"]
    )
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.session_state.negocio_id = None
        st.session_state.nombre_negocio = None
        st.session_state.mensajes_chat = []
        db.close()
        st.rerun()

    # --- SECCIÓN 1: GESTIÓN DE INVENTARIO ---
    if opcion_menu == "📦 Gestión de Inventario":
        st.subheader(f"📦 Inventario de {st.session_state.nombre_negocio}")

        productos = db.query(Producto).filter(Producto.negocio_id == st.session_state.negocio_id).all()

        if productos:
            data = [{"ID": p.id, "SKU": p.sku, "Nombre": p.nombre, "Precio": p.precio, "Stock": p.stock} for p in productos]
            df = pd.DataFrame(data)

            df_editado = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            if st.button("Guardar Cambios en la Nube"):
                for index, row in df_editado.iterrows():
                    prod_db = db.query(Producto).filter(Producto.id == row["ID"]).first()
                    if prod_db:
                        prod_db.precio = row["Precio"]
                        prod_db.stock = row["Stock"]
                        prod_db.nombre = row["Nombre"]
                db.commit()
                st.success("¡Inventario actualizado con éxito en PostgreSQL!")
        else:
            st.warning("Este negocio no tiene productos registrados en la base de datos.")

    # --- SECCIÓN 2: SOPORTE TÉCNICO DEL SISTEMA (AGNO) ---
    elif opcion_menu == "💬 Soporte Técnico del Sistema":
        st.subheader("🛠️ Asistente de Soporte Técnico del SaaS")
        st.caption("Resuelve dudas operativas, fallos de conexión y uso del panel en tiempo real.")

        # Mostrar historial de conversación actual
        for msg in st.session_state.mensajes_chat:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Caja de entrada para mensajes del usuario
        if prompt := st.chat_input("Escribe tu consulta técnica o problema aquí..."):
            st.session_state.mensajes_chat.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

            with st.chat_message("assistant"):
                negocio = db.query(NegocioConfig).filter(NegocioConfig.id == st.session_state.negocio_id).first()

                # SUPER PROMPT DE CONOCIMIENTO TÉCNICO Y DIAGNÓSTICO DEL SAAS
                conocimiento_sistema = (
                    "GUIA TECNICA Y PROTOCOLOS DE DIAGNOSTICO DEL SAAS DE AUTOMATIZACION DE VENTAS:\n\n"
                    "1. WHATSAPP / META API:\n"
                    "- Si el bot no responde: Verificar Token de Acceso (tokens temporales duran 24h, usar System User permanente). Verificar Webhook en Meta for Developers (debe estar Active y evento messages suscrito). Recordar ventana de 24h de Meta para mensajes libres.\n"
                    "- Si responde duplicado: Existen múltiples instancias activas del servidor o reintentos del Webhook de Meta si la API tarda mas de 3s en responder HTTP 200.\n\n"
                    "2. BASE DE DATOS Y PANEL:\n"
                    "- Si entrega precios desactualizados: El bot consulta PostgreSQL en tiempo real. Se debe actualizar en 'Gestion de Inventario' y presionar 'Guardar Cambios en la Nube'.\n"
                    "- Si no guarda cambios: Recordar presionar Enter en la celda antes de presionar el boton de guardar.\n\n"
                    "3. MODELOS DE IA:\n"
                    "- Errores de API: Verificar cuota en Google AI Studio y asegurar el uso del modelo oficial activo (Gemini 3.8 Flash).\n\n"
                    "4. GARANTIA (2 MESES):\n"
                    "- Cobertura: Corrección de fallos en codigo base, re-configuración de Webhooks/Servidores, ajustes de personalidad del agente y sincronización de datos.\n"
                    "- Escalar a Desarrollador Principal: Caída total del servidor de alojamiento (Render/VPS), pérdida de acceso a Meta Business Manager o nuevas funcionalidades."
                )

                try:
                    agente_soporte = Agent(
                        name="Ingeniero Soporte SaaS",
                        model=Gemini(id="gemini-3.8-flash"),
                        description="Eres el especialista senior en soporte técnico del SaaS de automatización de ventas para los administradores.",
                        instructions=[
                            f"Estás atendiendo al cliente/administrador de: '{negocio.nombre_negocio if negocio else 'Cliente'}'.",
                            "Actúa como un Ingeniero de Soporte Nivel 1 & 2 experto, servicial, calmado y muy pedagógico.",
                            "Cuando te reporten un problema, estructura tu respuesta en:",
                            "  1. Diagnóstico probable de lo que ocurre.",
                            "  2. Pasos numerados claros y directos que el usuario puede realizar por sí mismo.",
                            "  3. Confirmación de si la solución funcionó.",
                            f"Basa siempre tus soluciones en el manual técnico interno:\n{conocimiento_sistema}",
                            "Si el problema requiere cambios profundos de código o la caída del servidor principal, indícales amablemente que lo cubre su garantía de 2 meses y que lo reporte para una intervención técnica directa."
                        ],
                        markdown=True
                    )

                    response = agente_soporte.run(prompt)
                    respuesta_bot = response.content

                except Exception as e:
                    respuesta_bot = f"⚠️ Error al conectar con el soporte técnico: {e}"

                st.write(respuesta_bot)
                st.session_state.mensajes_chat.append({"role": "assistant", "content": respuesta_bot})

    db.close()