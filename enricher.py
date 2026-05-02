import re
from concurrent.futures import ThreadPoolExecutor
from ddgs import DDGS


# Verbos / preámbulos a strippear DEL INICIO del match (ej: "Tengo Coffeestar" -> "Coffeestar")
_LEADING_NOISE = {
    "tengo", "tuve", "soy", "estoy", "trabaje", "trabajé", "trabajo",
    "fui", "fue", "actualmente", "fundé", "fundo", "funde",
    "dirijo", "dirigí", "manejé", "manejo", "opero", "operé", "opere",
    "abrí", "abri", "compré", "compre", "vendo", "vendí", "vendi",
    "creé", "cree", "monté", "monte", "tuve",
    "dueño", "dueno", "socio", "fundador", "propietario",
}

# Palabras genéricas / ciudades a filtrar como nombre completo
_STOPWORDS = {
    "argentina", "mendoza", "cordoba", "córdoba", "tucuman", "tucumán",
    "rosario", "salta", "buenos aires", "caba", "capital", "federal",
    "mar del plata", "la plata", "san juan", "santa fe", "bahia blanca",
    "bahía blanca", "neuquen", "neuquén",
    "gastronomia", "gastronomía", "emprendimiento", "emprendedor",
    "experiencia", "años", "anos", "local", "negocio", "comercio",
}

# Prefijos típicos de rubro que ayudan a identificar nombres de marca
_GASTRO_PREFIX = (
    r"(?:Pizzer[ií]a|Caf[eé]|Cafeter[ií]a|Restaurante|Resto|Bar|"
    r"Hamburgueser[ií]a|Heladeria|Helader[ií]a|Panader[ií]a|"
    r"Sandwicher[ií]a|Cerveceria|Cerveceria|Parrilla)"
)

# 1-3 palabras tipo Title Case opcionalmente precedidas por un prefijo gastro
_NAME_PATTERN = re.compile(
    rf"((?:{_GASTRO_PREFIX})?\s*[A-ZÁÉÍÓÚÑ][\wñáéíóúü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wñáéíóúü]+){{0,2}})"
)


def _ddg_search(query: str, max_results: int = 3) -> list[dict]:
    """Una búsqueda en DuckDuckGo, sin API key."""
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
        print(f"[enricher] Error DuckDuckGo '{query}': {e}")
        return []


def _extract_business_names(experiencia: str, max_results: int = 4) -> list[str]:
    """
    Extrae nombres probables de negocios de un texto libre de experiencia.
    Ej: 'Tengo Coffeestar, Birka, La Forcheta, KobaKK y Pizzería Legui en Tucumán'
        -> ['Coffeestar', 'Birka', 'La Forcheta', 'KobaKK']
    """
    if not experiencia:
        return []

    # Separadores comunes en texto libre
    parts = re.split(r",|;|\.|\n|\s+y\s+|\s+e\s+|\s+-\s+|\|", experiencia)

    candidates: list[str] = []
    seen: set[str] = set()

    for part in parts:
        part = part.strip().rstrip(".,;:")
        if not part or len(part) > 80:
            continue

        for match in _NAME_PATTERN.finditer(part):
            name = match.group(1).strip()

            # Strip leading verbs / preámbulos ("Tengo Coffeestar" -> "Coffeestar")
            words = name.split()
            while words and words[0].lower() in _LEADING_NOISE:
                words = words[1:]
            if not words:
                continue
            name = " ".join(words)

            key = name.lower()
            if (
                key not in seen
                and len(name) >= 4
                and key not in _STOPWORDS
            ):
                seen.add(key)
                candidates.append(name)
                if len(candidates) >= max_results:
                    return candidates

    return candidates


def enriquecer_aplicante(aplicante: dict) -> dict:
    """
    Busca info pública con múltiples queries dirigidas en paralelo:
    1. Cada negocio declarado: '"Coffeestar" Tucumán'
    2. Perfil del candidato:    '"Juan Cruz Martín" Tucumán gastronomía emprendimiento'

    Esto permite verificar negocios específicos en lugar de buscar
    el nombre del candidato (que suele ser muy común).
    """
    nombre = (aplicante.get("nombre") or "").strip()
    ciudad = (aplicante.get("ciudad") or "").strip()
    experiencia = aplicante.get("experiencia_gastronomica") or ""

    if not nombre:
        return {"perfil_general": None, "negocios": [], "fuentes": []}

    negocios_declarados = _extract_business_names(experiencia, max_results=3)

    # Construir queries
    queries: list[tuple[str, str]] = []
    perfil_query = f'"{nombre}" {ciudad} gastronomía emprendimiento'.strip()
    queries.append(("perfil", perfil_query))
    for negocio in negocios_declarados:
        q = f'"{negocio}" {ciudad}'.strip() if ciudad else f'"{negocio}"'
        queries.append(("negocio", q))

    # Ejecutar todas en paralelo
    with ThreadPoolExecutor(max_workers=max(1, len(queries))) as pool:
        raw = list(pool.map(lambda q: (q[0], q[1], _ddg_search(q[1])), queries))

    # Organizar resultados
    perfil_resultados: list[dict] = []
    negocios_resultados: list[dict] = []
    fuentes: list[str] = []

    negocio_idx = 0
    for tipo, query, hits in raw:
        for h in hits:
            if h["url"] and h["url"] not in fuentes:
                fuentes.append(h["url"])
        if tipo == "perfil":
            perfil_resultados = hits
        else:
            negocio_name = negocios_declarados[negocio_idx] if negocio_idx < len(negocios_declarados) else query
            negocio_idx += 1
            negocios_resultados.append({
                "nombre": negocio_name,
                "query": query,
                "encontrado": len(hits) > 0,
                "resultados": hits,
            })

    return {
        "perfil_general": (
            {"query": perfil_query, "resultados": perfil_resultados}
            if perfil_resultados else None
        ),
        "negocios": negocios_resultados,
        "fuentes": fuentes,
    }


def formatear_para_scorer(enrichment: dict) -> str:
    """Render legible que se inserta en el prompt al modelo."""
    if not enrichment:
        return "No se encontró información pública adicional."

    partes: list[str] = []

    perfil = enrichment.get("perfil_general")
    if perfil and perfil.get("resultados"):
        partes.append("MENCIONES PÚBLICAS DEL CANDIDATO:")
        for r in perfil["resultados"]:
            partes.append(f"  - {r['titulo']}: {r['fragmento']}")

    negocios = enrichment.get("negocios", [])
    if negocios:
        if partes:
            partes.append("")
        partes.append("VERIFICACIÓN DE NEGOCIOS DECLARADOS:")
        for n in negocios:
            estado = "✓ ENCONTRADO" if n["encontrado"] else "✗ NO ENCONTRADO en internet"
            partes.append(f"  {estado}: {n['nombre']}")
            if n["encontrado"]:
                for r in n["resultados"][:2]:
                    partes.append(f"      · {r['titulo']}: {r['fragmento'][:200]}")

    if not partes:
        return "No se encontró información pública adicional."

    return "\n".join(partes)
