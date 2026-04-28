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
    Una sola búsqueda combinada para minimizar créditos de Tavily.
    """
    nombre = aplicante.get("nombre", "")
    ciudad = aplicante.get("ciudad", "")
    experiencia = aplicante.get("experiencia_gastronomica", "")

    enrichment = {
        "negocio": None,
        "perfil_general": None,
        "instagram": None,
        "fuentes": [],
    }

    # Una sola búsqueda combinada: nombre + ciudad + contexto gastronómico
    negocio = _extraer_nombre_negocio(experiencia)
    query = f'"{nombre}" {ciudad} {negocio} gastronomía emprendimiento'.strip()
    resultados = buscar_tavily(query, max_results=3)

    if resultados:
        enrichment["perfil_general"] = {
            "query": query,
            "resultados": resultados,
        }
        enrichment["fuentes"] = [r["url"] for r in resultados]

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
