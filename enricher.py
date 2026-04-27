import os
import requests

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"


def buscar_tavily(query: str, max_results: int = 3) -> list[dict]:
    """Hace una búsqueda en Tavily y devuelve resultados limpios."""
    if not TAVILY_API_KEY:
        return []
    try:
        response = requests.post(
            TAVILY_URL,
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=10,
        )
        data = response.json()
        resultados = []
        for r in data.get("results", []):
            resultados.append({
                "titulo": r.get("title", ""),
                "url": r.get("url", ""),
                "fragmento": r.get("content", "")[:300],
            })
        return resultados
    except Exception as e:
        print(f"Error en búsqueda Tavily: {e}")
        return []


def enriquecer_aplicante(aplicante: dict) -> dict:
    """
    Busca información pública del aplicante en internet.
    Devuelve un dict con lo que encontró, organizado por fuente.
    """
    nombre = aplicante.get("nombre", "")
    ciudad = aplicante.get("ciudad", "")
    instagram = aplicante.get("redes_sociales", "")
    experiencia = aplicante.get("experiencia_gastronomica", "")

    enrichment = {
        "negocio": None,
        "perfil_general": None,
        "instagram": None,
        "fuentes": [],
    }

    # 1. Buscar el negocio que declaró (si mencionó uno)
    palabras_clave_negocio = _extraer_nombre_negocio(experiencia)
    if palabras_clave_negocio:
        query_negocio = f"{palabras_clave_negocio} {ciudad} restaurante gastronomía"
        resultados = buscar_tavily(query_negocio, max_results=2)
        if resultados:
            enrichment["negocio"] = {
                "query": query_negocio,
                "resultados": resultados,
            }
            enrichment["fuentes"].extend([r["url"] for r in resultados])

    # 2. Buscar al candidato por nombre y ciudad
    query_persona = f'"{nombre}" {ciudad} gastronomía emprendimiento negocio'
    resultados_persona = buscar_tavily(query_persona, max_results=2)
    if resultados_persona:
        enrichment["perfil_general"] = {
            "query": query_persona,
            "resultados": resultados_persona,
        }
        enrichment["fuentes"].extend([r["url"] for r in resultados_persona])

    # 3. Verificar Instagram si lo proporcionó
    if instagram and "instagram.com" in instagram:
        handle = instagram.split("instagram.com/")[-1].strip("/")
        query_ig = f"instagram {handle} {ciudad}"
        resultados_ig = buscar_tavily(query_ig, max_results=1)
        if resultados_ig:
            enrichment["instagram"] = {
                "handle": handle,
                "resultados": resultados_ig,
            }

    enrichment["fuentes"] = list(set(enrichment["fuentes"]))
    return enrichment


def _extraer_nombre_negocio(experiencia: str) -> str:
    """
    Intenta extraer el nombre del negocio de la descripción de experiencia.
    Si no encuentra un nombre concreto, devuelve string vacío.
    """
    if not experiencia:
        return ""

    # Palabras que sugieren que mencionó un negocio propio
    keywords = ["pizzería", "cafetería", "restaurante", "bar", "hamburguesería",
                "local", "emprendimiento", "catering", "negocio"]

    for kw in keywords:
        if kw.lower() in experiencia.lower():
            # Devuelve los primeros 50 chars como contexto de búsqueda
            return experiencia[:60].strip()

    return ""


def formatear_para_scorer(enrichment: dict) -> str:
    """
    Convierte el enrichment en texto legible para incluir en el prompt del scorer.
    """
    if not enrichment:
        return "No se encontró información pública adicional."

    partes = []

    if enrichment.get("negocio"):
        partes.append("NEGOCIO ENCONTRADO EN INTERNET:")
        for r in enrichment["negocio"]["resultados"]:
            partes.append(f"  - {r['titulo']}: {r['fragmento']}")

    if enrichment.get("perfil_general"):
        partes.append("MENCIONES PÚBLICAS DEL CANDIDATO:")
        for r in enrichment["perfil_general"]["resultados"]:
            partes.append(f"  - {r['titulo']}: {r['fragmento']}")

    if enrichment.get("instagram"):
        partes.append("INSTAGRAM:")
        for r in enrichment["instagram"]["resultados"]:
            partes.append(f"  - {r['titulo']}: {r['fragmento']}")

    if not partes:
        return "Búsqueda realizada pero no se encontró información pública relevante."

    return "\n".join(partes)
