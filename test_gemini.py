import requests

API_KEY = "AQ.Ab8RN6Kgnd0mzuoF1_SSh735CY_Q8_e00DY_RJJYOxz1VmFx3w"

url = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/gemini-3.8-flash:generateContent"
)

headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": API_KEY,
}

data = {
    "contents": [
        {
            "parts": [
                {
                    "text": "Responde solamente: Hola, conexión exitosa."
                }
            ]
        }
    ]
}

response = requests.post(
    url,
    headers=headers,
    json=data,
)

print("STATUS:", response.status_code)
print("RESPONSE:")
print(response.text)