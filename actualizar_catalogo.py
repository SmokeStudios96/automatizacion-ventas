import json
import os
from database import SessionLocal, Producto, NegocioConfig

def actualizar_productos_ferreteria():
    if not os.path.exists("catalog.json"):
        print("❌ No se encontró catalog.json")
        return

    with open("catalog.json", "r", encoding="utf-8") as f:
        productos_json = json.load(f)

    db = SessionLocal()
    try:
        # 1. Obtener o crear el registro del negocio
        negocio = db.query(NegocioConfig).first()
        if not negocio:
            negocio = NegocioConfig(nombre="Ferretería Don Tito")
            db.add(negocio)
            db.commit()
            db.refresh(negocio)

        # 2. Limpiar productos antiguos del minimarket
        db.query(Producto).delete()
        db.commit()
        print("🗑️ Productos antiguos eliminados de la base de datos.")

        # 3. Insertar los productos de Ferretería Don Tito
        nuevos_productos = []
        for p in productos_json:
            nuevo = Producto(
                negocio_id=negocio.id,
                sku=p.get("sku"),
                nombre=p.get("nombre"),
                precio=p.get("precio"),
                stock=p.get("stock"),
                categoria=p.get("categoria")
            )
            nuevos_productos.append(nuevo)

        db.add_all(nuevos_productos)
        db.commit()
        print(f"✅ ¡Éxito! Se insertaron {len(nuevos_productos)} productos de Ferretería Don Tito en Supabase.")

    except Exception as e:
        db.rollback()
        print(f"❌ Error al actualizar la base de datos: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    actualizar_productos_ferreteria()