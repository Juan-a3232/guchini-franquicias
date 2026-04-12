import json
import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

CRITERIOS_GUCHINI = """
Sos el evaluador de franquicias de Guchini, la sandwichería viral de Mendoza.
Evaluá cada aplicante según estos criterios:

1. CAPITAL (peso: 30%)
   - Ideal: más de $20,000 USD
   - Aceptable: $15,000 - $20,000 USD
   - Insuficiente: menos de $15,000 USD

2. EXPERIENCIA GASTRONÓMICA (peso: 25%)
   - Ideal: tiene negocio gastronómico propio funcionando
   - Aceptable: experiencia en el rubro aunque sea en relación de dependencia
   - Insuficiente: sin ninguna experiencia en gastronomía

3. TIENE LOCAL (peso: 20%)
   - Ideal: tiene local propio o disponible en zona de alto tránsito
   - Aceptable: no tiene pero tiene plan concreto para conseguir uno
   - Insuficiente: no tiene y no mencionó cómo conseguirlo

4. MOTIVACIÓN Y FIT CON LA MARCA (peso: 15%)
   - Ideal: conoce la marca en profundidad, menciona a Federico, entiende el concepto
   - Aceptable: motivación genuina aunque sea vaga
   - Insuficiente: respuesta genérica o poco convincente

5. CIUDAD / MERCADO (peso: 10%)
   - Ideal: ciudad grande con potencial (CABA, Córdoba, Rosario) o ciudad donde Guchini quiere expandirse
   - Aceptable: ciudad mediana con mercado joven
   - Insuficiente: ciudad pequeña o saturada

Devolvé SIEMPRE un JSON con este formato exacto, sin texto adicional:
{
  "score": <número del 1 al 10 con un decimal>,
  "resumen": "<2 oraciones máximo describiendo al aplicante>",
  "fortalezas": ["<fortaleza 1>", "<fortaleza 2>"],
  "red_flags": ["<red flag 1>"],
  "recomendacion": "APROBAR" o "REVISAR" o "RECHAZAR"
}
"""

def evaluar_aplicante(aplicante: dict) -> dict:
    prompt = f"""
{CRITERIOS_GUCHINI}

Aplicante a evaluar:
{json.dumps(aplicante, ensure_ascii=False, indent=2)}

Devolvé solo el JSON, sin texto adicional, sin bloques de código.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def evaluar_todos(aplicantes: list) -> list:
    resultados = []
    for aplicante in aplicantes:
        print(f"Evaluando {aplicante['nombre']}...")
        evaluacion = evaluar_aplicante(aplicante)
        resultados.append({**aplicante, "evaluacion": evaluacion})
    resultados.sort(key=lambda x: x["evaluacion"]["score"], reverse=True)
    return resultados


if __name__ == "__main__":
    with open("mock_data.json", encoding="utf-8") as f:
        aplicantes = json.load(f)

    resultados = evaluar_todos(aplicantes)

    with open("resultados.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    print("\n=== RANKING FINAL ===")
    for i, r in enumerate(resultados, 1):
        e = r["evaluacion"]
        print(f"{i}. {r['nombre']} ({r['ciudad']}) — Score: {e['score']} — {e['recomendacion']}")
