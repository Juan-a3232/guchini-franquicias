from duckduckgo_search import DDGS


def buscar_duckduckgo(query: str, max_results: int = 3) -> list[dict]:
    """Busca en DuckDuckGo gratis, sin API key."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {
                "titulo": r.get("title", ""),
                "url": r.get("href", ""),
                "fragmento": r.get("body", "")[:300],
            }
            for r in results
        ]
    except Exception as e:
        print(f"[enricher] Error DuckDuckGo: {e}")
        return []


def enriquecer_aplicante(aplicante: dict) -> dict:
    """Busca información pública del aplicante en DuckDuckGo."""
    nombre = aplicante.get("nombre", "")
    ciudad = aplicante.get("ciudad", "")
    experiencia = aplicante.get("experiencia_gastronomica", "")

    negocio = _extraer_nombre_negocio(experiencia)
    query = f'"{nombre}" {ciudad} {negocio} gastronomía emprendimiento'.strip()
    resultados = buscar_duckduckgo(query, max_results=3)

    enrichment = {"perfil_general": None, "fuentes": []}
    if resultados:
        enrichment["perfil_general"] = {"query": query, "resultados": resultados}
        enrichment["fuentes"] = [r["url"] for r in resultados]

    return enrichment


def _extraer_nombre_negocio(experiencia: str) -> str:
    if not experiencia:
        return ""
    keywords = ["pizzería", "cafetería", "restaurante", "bar", "hamburguesería",
                "local", "emprendimiento", "catering", "negocio"]
    for kw in keywords:
        if kw.lower() in experiencia.lower():
            return experiencia[:60].strip()
    return ""


def formatear_para_scorer(enrichment: dict) -> str:
    if not enrichment or not enrichment.get("perfil_general"):
        return "No se encontró información pública adicional."
    partes = ["MENCIONES PÚBLICAS DEL CANDIDATO:"]
    for r in enrichment["perfil_general"]["resultados"]:
        partes.append(f"  - {r['titulo']}: {r['fragmento']}")
    return "\n".join(partes)
