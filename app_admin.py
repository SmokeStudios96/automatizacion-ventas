import streamlit as st
import pandas as pd
from database import SessionLocal, Producto, NegocioConfig

st.title("🛠️ Panel de Gestión - Agente WhatsApp")

db = SessionLocal()

# Selector de negocio (Multi-tenant)
negocios = db.query(NegocioConfig).all()
negocio_nombres = {n.nombre_negocio: n.id for n in negocios}

if negocio_nombres:
    seleccion_negocio = st.selectbox("Selecciona el Negocio", list(negocio_nombres.keys()))
    negocio_id = negocio_nombres[seleccion_negocio]

    st.subheader(f"Inventario para: {seleccion_negocio}")

    # Cargar productos de ese negocio en un DataFrame editable
    productos = db.query(Producto).filter(Producto.negocio_id == negocio_id).all()

    if productos:
        data = [{"ID": p.id, "SKU": p.sku, "Nombre": p.nombre, "Precio": p.precio, "Stock": p.stock} for p in productos]
        df = pd.DataFrame(data)

        # Tabla interactiva editable
        df_editado = st.data_editor(df, num_rows="dynamic")

        if st.button("Guardar Cambios en la Nube"):
            # Aquí actualizas la base de datos con los cambios del DataFrame
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
else:
    st.error("No hay negocios registrados en la base de datos.")

db.close()