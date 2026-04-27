import json
import os
from groq import Groq
from enricher import enriquecer_aplicante, formatear_para_scorer

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

CRITERIOS_GUCHINI = """
Sos el evaluador de franquicias de Guchini, la sandwichería viral de Mendoza, Argentina.
La inversión total real de una franquicia Guchini es de aproximadamente USD 105.000.
Evaluá cada aplicante según estos criterios con total rigor:

1. CAPACIDAD FINANCIERA (peso: 30%)
   - Ideal: capital disponible mayor a USD 105.000 (puede cubrir inversión completa sin financiamiento)
   - Aceptable: USD 70.000 - USD 105.000 (necesita financiamiento parcial pero es viable)
   - En revisión: USD 40.000 - USD 70.000 (necesita financiamiento significativo, riesgo alto)
   - Insuficiente: menos de USD 40.000 (no puede afrontar la inversión, descartable)

2. PERFIL COMERCIAL Y LIDERAZGO (peso: 25%)
   - Ideal: emprendedor con negocio propio exitoso, manejo de equipos, experiencia en ventas o gastronomía
   - Aceptable: experiencia comercial sólida aunque sea en relación de dependencia, con manejo de personas
   - Insuficiente: sin experiencia comercial ni liderazgo, perfil puramente técnico o sin historial relevante

3. DISPONIBILIDAD OPERATIVA (peso: 20%)
   - Ideal: el franquiciado opera el local personalmente y a tiempo completo (no es inversor pasivo)
   - Aceptable: tiene un gerente identificado y aprobado por Guchini, con supervisión activa del franquiciado
   - Insuficiente: quiere ser inversor pasivo sin involucramiento operativo, o no tiene plan operativo claro

4. MOTIVACIÓN Y FIT CON LA MARCA (peso: 15%)
   - Ideal: conoce a Federico Robello, entiende el concepto viral de Guchini, menciona el producto específico, tiene convicción real
   - Aceptable: motivación genuina y conocimiento básico de la marca, aunque superficial
   - Insuficiente: respuesta genérica, no conoce la marca en profundidad, o busca solo retorno financiero

5. CIUDAD Y MERCADO (peso: 10%)
   - Ideal: ciudades prioritarias Año 1 (Córdoba, CABA, Mar del Plata, Bahía Blanca) con potencial de alto tránsito
   - Aceptable: ciudad mediana con mercado joven y sin saturación del rubro sandwiches premium
   - Insuficiente: ciudad pequeña, mercado saturado, o ciudad donde Guchini ya tiene presencia (Mendoza)

IMPORTANTE — Sé extremadamente estricto:
- Reservá 9-10 SOLO para candidatos excepcionales en TODOS los criterios
- Ningún candidato sin capital suficiente (menos de USD 70K) puede pasar de 6.5
- La disponibilidad operativa personal es NO NEGOCIABLE para Guchini — penalizá fuerte al inversor pasivo
- Usá el rango completo del 1 al 10, con decimales

Devolvé SIEMPRE un JSON con este formato exacto, sin texto adicional:
{
  "score": <número del 1 al 10 con un decimal>,
  "breakdown": {
    "capital": <número del 1 al 10>,
    "perfil_comercial": <número del 1 al 10>,
    "disponibilidad": <número del 1 al 10>,
    "motivacion": <número del 1 al 10>,
    "ciudad": <número del 1 al 10>
  },
  "resumen": "<3 a 4 oraciones describiendo al aplicante: quién es, qué tiene a favor, qué le falta, y por qué es o no es un buen candidato para Guchini>",
  "fortalezas": ["<fortaleza 1>", "<fortaleza 2>", "<fortaleza 3 si aplica>"],
  "red_flags": ["<red flag 1>", "<red flag 2 si aplica>"],
  "recomendacion": "APROBAR" o "REVISAR" o "RECHAZAR"
}
"""

def evaluar_aplicante(aplicante: dict) -> dict:
    # Enriquecer con datos públicos de internet
    enrichment = enriquecer_aplicante(aplicante)
    info_publica = formatear_para_scorer(enrichment)

    prompt = f"""
{CRITERIOS_GUCHINI}

Aplicante a evaluar:
{json.dumps(aplicante, ensure_ascii=False, indent=2)}

Información pública encontrada en internet sobre este candidato:
{info_publica}

Usá la información pública para validar o cuestionar lo que declaró el candidato.
Si encontraste su negocio online y tiene buenas reseñas, es una señal positiva.
Si no encontraste nada de lo que declaró, mencionalo como red flag.
Si encontraste inconsistencias entre lo declarado y lo encontrado, bajá el score.

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
