import os
import requests
from typing import Dict, Any, List

BSALE_ACCESS_TOKEN = os.environ.get("BSALE_ACCESS_TOKEN", "")
BSALE_BASE_URL = "https://api.bsale.cl/v1"

def _get_headers() -> Dict[str, str]:
    return {
        "access_token": BSALE_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

def generar_boleta_bsale(items: List[Dict[str, Any]], phone_number: str) -> Dict[str, Any]:
    """
    Genera una boleta electrónica en BSale a partir de la lista de productos del carrito.
    """
    if not BSALE_ACCESS_TOKEN:
        return {
            "success": False,
            "error": "Falta configurar la variable de entorno 'BSALE_ACCESS_TOKEN'."
        }

    try:
        # 1. Definir los detalles de los productos para la API de BSale
        details = []
        for item in items:
            details.append({
                "netUnitValue": round(float(item.get("precio_unitario", 0)) / 1.19, 2),  # Valor neto aproximado
                "quantity": int(item.get("cantidad", 1)),
                "taxId": "[1]",  # IVA 19% por defecto en Chile
                "comment": f"SKU: {item.get('sku', '')} - {item.get('nombre_producto', '')}"
            })

        # 2. Estructura del Payload para BSale
        payload = {
            "documentTypeId": 1,   # 1 suele ser Boleta Electrónica en BSale (verificar con cliente)
            "officeId": 1,         # ID Sucursal principal
            "priceListId": 1,      # ID Lista de precios estándar
            "declareSii": 1,        # 1 = Enviar a SII inmediatamente
            "details": details,
            "client": {
                "company": "Cliente WhatsApp",
                "phone": phone_number
            }
        }

        # 3. Realizar petición a la API
        response = requests.post(
            f"{BSALE_BASE_URL}/documents.json",
            headers=_get_headers(),
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            data = response.json()
            return {
                "success": True,
                "bsale_id": data.get("id"),
                "url_pdf": data.get("urlPdf"),
                "number": data.get("number")
            }
        else:
            return {
                "success": False,
                "error": f"Error BSale ({response.status_code}): {response.text}"
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Excepción al conectar con BSale: {str(e)}"
        }