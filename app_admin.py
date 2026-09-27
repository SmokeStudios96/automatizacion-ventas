import streamlit as st
import pandas as pd
from database import SessionLocal, Producto, NegocioConfig

st.title("🛠️ Panel de Gestión - Agente WhatsApp")

# Inicializar estado de sesión para el login
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.negocio_id = None
    st.session_state.nombre_negocio = None

db = SessionLocal()

# Pantalla de Login si no ha iniciado sesión
if not st.session_state.autenticado:
    st.subheader("🔐 Acceso al Panel de Gestión")
    
    usuario_ingresado = st.text_input("Usuario")
    password_ingresada = st.text_input("Contraseña", type="password")
    
    if st.button("Ingresar"):
        # Buscar el negocio por usuario y contraseña
        negocio = db.query(NegocioConfig).filter(
            NegocioConfig.usuario == usuario_ingresado,
            NegocioConfig.password == password_ingresada
        ).first()
        
        if negocio:
            st.session_state.autenticado = True
            st.session_state.negocio_id = negocio.id
            st.session_state.nombre_negocio = negocio.nombre_negocio
            st.success(f"¡Bienvenido, {negocio.nombre_negocio}!")
            db.close()
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos")
    db.close()
    
else:
    # --- PANEL DE GESTIÓN PRIVADO (Filtrado por el negocio autenticado) ---
    st.sidebar.write(f"Conectado como: **{st.session_state.nombre_negocio}**")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.session_state.negocio_id = None
        st.session_state.nombre_negocio = None
        db.close()
        st.rerun()

    st.subheader(f"Inventario para: {st.session_state.nombre_negocio}")

    # Cargar productos exclusivamente de ese negocio en un DataFrame editable
    productos = db.query(Producto).filter(Producto.negocio_id == st.session_state.negocio_id).all()

    if productos:
        data = [{"ID": p.id, "SKU": p.sku, "Nombre": p.nombre, "Precio": p.precio, "Stock": p.stock} for p in productos]
        df = pd.DataFrame(data)

        # Tabla interactiva editable
        df_editado = st.data_editor(df, num_rows="dynamic")

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
        st.warning("Este negocio no tiene productos registrados.")
        
    db.close()