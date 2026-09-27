import streamlit as st
import pandas as pd
from database import SessionLocal, Producto, NegocioConfig, HistorialMensaje

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
                {"role": "assistant", "content": f"¡Hola! Soy el asistente IA de **{negocio.nombre_negocio}**. ¿En qué te puedo ayudar hoy con el soporte o el inventario?"}
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

    # --- SECCIÓN 1: CHAT CON AGENTE IA ---
    if opcion_menu == "💬 Chat con Agente IA":
        st.subheader("🤖 Asistente de Soporte & Consultas en Vivo")
        st.caption("Interactúa directamente con el agente inteligente de tu negocio.")

        # Mostrar historial de conversación actual en la interfaz
        for msg in st.session_state.mensajes_chat:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Caja de entrada para mensajes del usuario
        if prompt := st.chat_input("Escribe tu consulta o soporte aquí..."):
            # Mostrar mensaje del usuario
            st.session_state.mensajes_chat.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

            # Lógica simple de respuesta del agente (Soporte + Consulta de Inventario)
            with st.chat_message("assistant"):
                # Consultar productos del negocio
                productos = db.query(Producto).filter(Producto.negocio_id == st.session_state.negocio_id).all()
                prod_info = "\n".join([f"- {p.nombre} (SKU: {p.sku}): ${p.precio:.0f} | Stock: {p.stock}" for p in productos]) if productos else "No hay productos registrados."

                # Respuesta simulada/asistida por el inventario (se puede conectar a Gemini API más adelante)
                respuesta_bot = f"Recibido tu mensaje: *'{prompt}'*.\n\nActualmente en tu base de datos tienes estos productos registrados:\n{prod_info}"
                
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