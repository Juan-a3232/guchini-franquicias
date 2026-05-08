import asyncio
import json
import os
from anthropic import AsyncAnthropic
from enricher import enriquecer_aplicante, formatear_para_scorer

client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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
   - Ideal: ciudades target de expansión (Córdoba, CABA, Mar del Plata, Bahía Blanca, Rosario, Santa Fe, La Plata, Tucumán, Salta) con potencial de alto tránsito y mercado joven
   - Aceptable: ciudad mediana con mercado joven y sin saturación del rubro sandwiches premium
   - Insuficiente: ciudad pequeña, mercado saturado, o ciudad donde Guchini ya tiene presencia (Mendoza, San Rafael)

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

FALLBACK_EVALUACION = {
    "score": 5.0,
    "breakdown": {"capital": 5, "perfil_comercial": 5, "disponibilidad": 5, "motivacion": 5, "ciudad": 5},
    "resumen": "No se pudo evaluar automáticamente. Requiere revisión manual.",
    "fortalezas": [],
    "red_flags": ["Error en evaluación automática"],
    "recomendacion": "REVISAR",
}


def _parse_json_response(raw: str) -> dict:
    """Extract and parse JSON from model response, handling extra text around the object."""
    raw = raw.strip()
    # Find first { and last } to extract the JSON object regardless of surrounding text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {raw[:200]}")
    return json.loads(raw[start:end + 1])


async def evaluar_aplicante_async(aplicante: dict) -> tuple[dict, list[str]]:
    loop = asyncio.get_event_loop()
    enrichment = await loop.run_in_executor(None, enriquecer_aplicante, aplicante)
    info_publica = formatear_para_scorer(enrichment)
    fuentes = enrichment.get("fuentes", [])

    prompt = f"""
{CRITERIOS_GUCHINI}

Aplicante a evaluar:
{json.dumps(aplicante, ensure_ascii=False, indent=2)}

Información pública encontrada en internet sobre este candidato:
{info_publica}

ADVERTENCIA: la info de internet puede ser de otra persona con el mismo nombre.
SOLO usá datos web que confirmen exactamente lo que el candidato declaró (mismo nombre de negocio, misma ciudad).
Si la info web menciona cosas que el candidato NO declaró (otros negocios, logros, menciones en medios), IGNORALA — probablemente es otra persona.
Usá internet únicamente para VERIFICAR lo declarado, nunca para AGREGAR información nueva.
Si el negocio declarado aparece online con buenas reseñas, es señal positiva.
Si no encontraste nada de lo declarado, mencionalo como red flag menor (no como descarte).

Devolvé solo el JSON, sin texto adicional, sin bloques de código.
"""

    message = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    return _parse_json_response(raw), fuentes


def _safe_score(r: dict) -> float:
    """Safe score extraction — returns 0.0 if score is missing or non-numeric."""
    try:
        return float(r["evaluacion"]["score"])
    except (TypeError, ValueError, KeyError):
        return 0.0


async def evaluar_todos_async(aplicantes: list, on_progress=None) -> list:
    semaphore = asyncio.Semaphore(2)
    resultados = []

    async def eval_one(aplicante):
        async with semaphore:
            try:
                evaluacion, fuentes = await evaluar_aplicante_async(aplicante)
            except Exception as e:
                print(f"[scorer] Error evaluando {aplicante.get('nombre', '?')}: {e}")
                evaluacion = FALLBACK_EVALUACION.copy()
                fuentes = []
            resultado = {**aplicante, "evaluacion": evaluacion, "fuentes_web": fuentes}
            if on_progress:
                on_progress(resultado)
            return resultado

    tasks = [eval_one(a) for a in aplicantes]
    resultados = await asyncio.gather(*tasks)
    resultados = list(resultados)
    resultados.sort(key=_safe_score, reverse=True)
    return resultados


# Sync wrapper for backward compatibility (e.g. CLI testing)
def evaluar_todos(aplicantes: list) -> list:
    return asyncio.run(evaluar_todos_async(aplicantes))


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
