from agent_whatsapp import ask_agent

# Simulamos el número de un cliente y su pregunta sobre el catálogo
telefono_prueba = "56912345678"
pregunta_cliente = "Hola, ¿tienen stock del cemento o algún adhesivo y cuánto cuesta?"

print(f"--- SIMULANDO MENSAJE DE CLIENTE ({telefono_prueba}) ---")
print(f"Mensaje: {pregunta_cliente}\n")

# Ejecutamos la función que consulta la base de datos y a Gemini
respuesta = ask_agent(pregunta_cliente, telefono_prueba)

print("--- RESPUESTA DEL BOT ---")
print(respuesta)