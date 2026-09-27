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
                {"role": "assistant", "content": f"¡Hola! Soy el asistente técnico de **{negocio.nombre_negocio}**. ¿En qué te puedo ayudar hoy con el soporte o el inventario?"}
            ]
            st.success(f"¡Bienvenido, {negocio.nombre_negocio}!")
            db.close()
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos")
    db.close()

else:
    # 3. Menú Lateral de Navegación una vez autenticado
    st.sidebar.markdown(f"### 🏢 **{st.session_state.nombre_negocio}**")
    
    opcion_menu = st.sidebar.radio(
        "Selecciona una opción:",
        ["💬 Chat con Agente IA", "📦 Gestión de Inventario"]
    )
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.session_state.negocio_id = None
        st.session_state.nombre_negocio = None
        st.session_state.mensajes_chat = []
        db.close()
        st.rerun()

    # --- SECCIÓN 1: CHAT CON AGENTE IA (AGNO) ---
    if opcion_menu == "💬 Chat con Agente IA":
        st.subheader("🤖 Agente IA de Soporte Técnico & Consultas en Vivo")
        st.caption("Asistente inteligente impulsado por Agno y Gemini.")

        # Mostrar historial de conversación actual
        for msg in st.session_state.mensajes_chat:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Caja de entrada para mensajes del usuario
        if prompt := st.chat_input("Escribe tu consulta de soporte o inventario aquí..."):
            st.session_state.mensajes_chat.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

            with st.chat_message("assistant"):
                # Cargar datos del negocio e inventario desde PostgreSQL
                negocio = db.query(NegocioConfig).filter(NegocioConfig.id == st.session_state.negocio_id).first()
                productos = db.query(Producto).filter(Producto.negocio_id == st.session_state.negocio_id).all()
                
                prod_info = "\n".join([f"- {p.nombre} (SKU: {p.sku}): ${p.precio:.0f} | Stock: {p.stock}" for p in productos]) if productos else "No hay productos registrados."

                try:
                    # Instanciar el agente Agno adaptado a las configuraciones del negocio
                    agente_soporte = Agent(
                        name=f"Soporte {negocio.nombre_negocio if negocio else 'SaaS'}",
                        model=Gemini(id="gemini-2.5-flash"),
                        description=f"Eres un agente de soporte técnico experto y atención al cliente para {negocio.nombre_negocio if negocio else 'el negocio'}.",
                        instructions=[
                            f"Tu personalidad asignada: {negocio.persona_ia if negocio and negocio.persona_ia else 'Asistente técnico amable'}",
                            f"Reglas de atención: {negocio.reglas_atencion if negocio and negocio.reglas_atencion else 'Responder breve y claro.'}",
                            "Ayuda a los clientes a resolver problemas técnicos, recomendar materiales y orientar sobre compras.",
                            f"Consulta el siguiente INVENTARIO ACTUALIZADO para dar precios y verificar stock:\n{prod_info}",
                            "Si te preguntan por un producto fuera de la lista, indica de forma educada que no está disponible."
                        ],
                        markdown=True
                    )

                    # Ejecutar el agente con Agno
                    response = agente_soporte.run(prompt)
                    respuesta_bot = response.content

                except Exception as e:
                    respuesta_bot = f"⚠️ Error al conectar con el agente Agno: {e}"

                st.write(respuesta_bot)
                st.session_state.mensajes_chat.append({"role": "assistant", "content": respuesta_bot})

    # --- SECCIÓN 2: GESTIÓN DE INVENTARIO ---
    elif opcion_menu == "📦 Gestión de Inventario":
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

    db.close()