import os
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

# ==============================================================================
# SELECTOR DE AGENTE ACTIVO PARA DEMOS EN VIVO
# Descomenta únicamente el agente que deseas mostrar en este momento:
# ==============================================================================

from agent_estetica import app      # 1. Ona Songailaite (Estética / PMU)
# from agent_dental import app        # 2. Clínica Dental
# from agent_ferreteria import app    # 3. Ferretería Don Tito

# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)