import os
import json
from dotenv import load_dotenv

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

from supabase import create_client, Client
from bsale_client import generar_boleta_bsale

# ------------------------------------------------------------------------------
# 1. Configuración de Supabase para la herramienta de Carrito
# ------------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan las variables de entorno SUPABASE_URL o SUPABASE_KEY en el archivo .env o en el entorno.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Número de teléfono fallback para el simulador CLI en caso de no recibir uno en el contexto
DEFAULT_PHONE = "+56912345678"

# ------------------------------------------------------------------------------
# 2. Herramientas del Carrito (Agno Tools)
# ------------------------------------------------------------------------------

def agregar_al_carrito(phone_number: str = DEFAULT_PHONE, sku: str = "", cantidad: int = 1) -> str:
    """
    Agrega un producto al carrito de compras del cliente basándose en su número de teléfono.
    """
    try:
        num = phone_number if phone_number and phone_number.strip() else DEFAULT_PHONE
        
        # Cargar catálogo local para obtener detalles del producto
        with open("catalog.json", "r", encoding="utf-8") as f:
            catalog = json.load(f)
            
        producto = next((p for p in catalog if p["sku"].upper() == sku.upper()), None)
        if not producto:
            return f"Error: No se encontró ningún producto con el SKU '{sku}' en el catálogo."
            
        if producto.get("stock", 0) < cantidad:
            return f"Stock insuficiente para '{producto['nombre']}'. Stock disponible: {producto.get('stock', 0)} unidades."

        # Verificar si el ítem ya existe en la tabla 'carritos'
        res = supabase.table("carritos").select("*").eq("phone_number", num).eq("sku", sku).execute()
        
        if res.data and len(res.data) > 0:
            item_existente = res.data[0]
            nueva_cantidad = int(item_existente["cantidad"]) + cantidad
            supabase.table("carritos").update({"cantidad": nueva_cantidad}).eq("id", item_existente["id"]).execute()
        else:
            nuevo_item = {
                "phone_number": num,
                "bsale_variant_id": str(producto.get("bsale_variant_id", "")),
                "sku": producto["sku"],
                "nombre_producto": producto["nombre"],
                "cantidad": cantidad,
                "precio_unitario": producto["precio"]
            }
            supabase.table("carritos").insert(nuevo_item).execute()

        return f"Éxito: Se agregaron {cantidad} unidad(es) de '{producto['nombre']}' al carrito."
    except Exception as e:
        print(f"DEBUG ERROR EN AGREGAR_AL_CARRITO: {e}")
        return f"Error al agregar producto al carrito: {str(e)}"


def ver_carrito(phone_number: str = DEFAULT_PHONE) -> str:
    """
    Muestra el contenido actual del carrito de compras del cliente y calcula el subtotal.
    Usa esta función SIEMPRE que el cliente pregunte qué tiene en su carrito, qué ha agregado o cuál es el total acumulado.
    """
    try:
        num = phone_number if phone_number and phone_number.strip() else DEFAULT_PHONE

        res = supabase.table("carritos").select("*").eq("phone_number", num).execute()
        items = res.data

        if not items:
            return "El carrito de compras está actualmente vacío."

        resumen = "🛒 **Carrito de Compras Actual:**\n"
        total = 0.0
        for item in items:
            precio = float(item.get("precio_unitario", 0) or 0)
            cant = int(item.get("cantidad", 1) or 1)
            subtotal = cant * precio
            total += subtotal
            resumen += f"- {item.get('nombre_producto', 'Producto')} (SKU: {item.get('sku', 'N/A')}) x{cant} = ${subtotal:,.0f} CLP\n"

        resumen += f"\n**Total estimado:** ${total:,.0f} CLP"
        return resumen
    except Exception as e:
        print(f"DEBUG ERROR EN VER_CARRITO: {e}")
        return f"Error al consultar el carrito: {str(e)}"


def procesar_cierre_pedido(phone_number: str = DEFAULT_PHONE) -> str:
    """
    Cierra el carrito activo, emite la boleta electrónica en BSale (si está configurado) 
    o registra el pedido en Supabase como respaldo, descuenta el stock en la tabla productos y vacía el carrito.
    """
    try:
        num = phone_number if phone_number and phone_number.strip() else DEFAULT_PHONE

        # 1. Obtener los ítems del carrito
        res = supabase.table("carritos").select("*").eq("phone_number", num).execute()
        items = res.data

        if not items:
            return "No se puede procesar el pedido porque el carrito está vacío."

        # 2. Calcular total de forma segura
        monto_total = 0.0
        for item in items:
            precio = float(item.get("precio_unitario", 0) or 0)
            cant = int(item.get("cantidad", 1) or 1)
            monto_total += cant * precio
        
        # 3. Generar código único de pedido
        codigo_pedido = f"PED-{num[-4:]}-{os.urandom(2).hex().upper()}"

        # 4. Intentar emitir boleta electrónica en BSale
        resultado_bsale = generar_boleta_bsale(items, num)

        bsale_document_id = None
        url_pdf = None
        estado_pedido = "pendiente"
        origen_pedido = "SUPABASE_FALLBACK"

        if resultado_bsale.get("success"):
            bsale_document_id = str(resultado_bsale.get("bsale_id"))
            url_pdf = resultado_bsale.get("url_pdf")
            estado_pedido = "facturado_bsale"
            origen_pedido = "BSALE_OFFICIAL"

        # 5. Registrar en la tabla 'pedidos' de Supabase
        nuevo_pedido = {
            "codigo_pedido": codigo_pedido,
            "phone_number": num,
            "origen": origen_pedido,
            "bsale_document_id": bsale_document_id,
            "monto_total": monto_total,
            "items": items,
            "estado": estado_pedido
        }
        
        supabase.table("pedidos").insert(nuevo_pedido).execute()

        # 5.1 Descontar el stock de cada producto en la tabla 'productos'
        for item in items:
            sku_item = item.get("sku")
            cant_comprada = int(item.get("cantidad", 1))
            
            prod_res = supabase.table("productos").select("stock").eq("sku", sku_item).execute()
            if prod_res.data and len(prod_res.data) > 0:
                stock_actual = int(prod_res.data[0].get("stock", 0))
                nuevo_stock = max(0, stock_actual - cant_comprada)
                
                supabase.table("productos").update({"stock": nuevo_stock}).eq("sku", sku_item).execute()

        # 6. Vaciar el carrito
        supabase.table("carritos").delete().eq("phone_number", num).execute()

        # 7. Construir respuesta final
        respuesta = (
            f"✅ **¡Pedido registrado con éxito!**\n\n"
            f"Código de Pedido: **{codigo_pedido}**\n"
            f"Monto Total: **${monto_total:,.0f} CLP**\n"
        )

        if url_pdf:
            respuesta += f"\n📄 Boleta Electrónica emitida: [Descargar Boleta PDF]({url_pdf})\n"
            respuesta += "¡Muchas gracias por su compra!"
        else:
            respuesta += "\nTu orden ha quedado registrada. Nos pondremos en contacto para gestionar la entrega y pago."

        return respuesta

    except Exception as e:
        print(f"DEBUG ERROR EN PROCESAR_CIERRE_PEDIDO: {e}")
        return f"Error al procesar el cierre del pedido: {str(e)}"