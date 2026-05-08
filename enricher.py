"""
enricher.py — Búsqueda de perfiles en redes sociales y páginas de negocios.
- Candidato: Instagram, TikTok, LinkedIn (solo si nombre + ciudad coinciden exactamente)
- Negocio declarado: Instagram, TikTok, web (si mencionó un nombre de negocio)
No influye en el score — solo se usa para mostrar links en la tarjeta.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from ddgs import DDGS

_DDG_REGION = "ar-es"

_CIUDADES_INVALIDAS = {
    "si es otro lugar",
    "internacional",
    "otra",
    "sin especificar",
}

# Verbos/preámbulos a ignorar al extraer nombres de negocios
_LEADING_NOISE = {
    "tengo", "tuve", "soy", "trabaje", "trabajé", "trabajo", "fui", "fue",
    "actualmente", "fundé", "fundo", "dirijo", "dirigí", "manejé", "manejo",
    "opero", "abrí", "abri", "creé", "monté", "monte", "dueño", "dueno",
    "socio", "fundador", "propietario",
}
_STOPWORDS = {
    # Ciudades
    "argentina", "mendoza", "cordoba", "córdoba", "tucuman", "tucumán",
    "rosario", "salta", "buenos aires", "caba", "capital", "federal",
    "mar del plata", "la plata", "san juan", "santa fe", "bahia blanca",
    "bahía blanca", "neuquen", "neuquén",
    # Términos gastronómicos genéricos
    "gastronomia", "gastronomía", "emprendimiento", "emprendedor",
    "experiencia", "años", "local", "negocio", "comercio",
    # Conectores y palabras de inicio de oración (no son nombres de negocio)
    "además", "ademas", "también", "tambien", "porque", "pero", "hace",
    "como", "cuando", "donde", "quien", "cual", "esto", "esta", "estas",
    "para", "desde", "hasta", "entre", "sobre", "bajo", "creo", "tengo",
    "tiene", "tuve", "sido", "estar", "siendo", "quiero", "puedo", "puede",
    "tiene", "con", "sin", "por", "una", "uno", "del", "los", "las",
    "soy", "fue", "fui", "hay", "hoy", "así", "asi", "si", "no", "ya",
    # Marca que quieren franquiciar (no es su negocio)
    "guchini",
}
_GASTRO_PREFIX = (
    r"(?:Pizzer[ií]a|Caf[eé]|Cafeter[ií]a|Restaurante|Resto|Bar|"
    r"Hamburgueser[ií]a|Helader[ií]a|Panader[ií]a|Sandwicher[ií]a|Parrilla|"
    r"Heladeria|Cerveceria|Vermutería|Vermuteria)"
)
# Requiere prefijo gastronómico O al menos 2 palabras en Title Case para ser nombre de negocio
_NAME_PATTERN = re.compile(
    rf"((?:{_GASTRO_PREFIX})\s*[A-ZÁÉÍÓÚÑ][\wñáéíóúü]*(?:\s+[A-ZÁÉÍÓÚÑ][\wñáéíóúü]+){{0,2}}"
    rf"|[A-ZÁÉÍÓÚÑ][\wñáéíóúü]{{2,}}\s+[A-ZÁÉÍÓÚÑ][\wñáéíóúü]{{2,}}(?:\s+[A-ZÁÉÍÓÚÑ][\wñáéíóúü]+){{0,1}})"
)


def _ddg_search(query: str, max_results: int = 3, retries: int = 2) -> list[dict]:
    last_err = None
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region=_DDG_REGION, max_results=max_results))
            return [
                {
                    "url": r.get("href", ""),
                    "texto": (r.get("title", "") + " " + r.get("body", ""))[:400],
                }
                for r in results
            ]
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 + attempt)
    print(f"[enricher] DDG error '{query}': {last_err}")
    return []


def _ciudad_valida(ciudad: str) -> bool:
    c = ciudad.lower().strip()
    return bool(c) and not any(inv in c for inv in _CIUDADES_INVALIDAS)


def _match_nombre(texto: str, nombre: str) -> bool:
    """Verdadero si todas las partes del nombre aparecen en el texto."""
    t = texto.lower()
    partes = nombre.lower().split()
    return all(p in t for p in partes) if len(partes) >= 2 else nombre.lower() in t


def _match_ciudad(texto: str, ciudad: str) -> bool:
    return ciudad.lower() in texto.lower()


def _extract_business_names(experiencia: str, max_results: int = 3) -> list[str]:
    if not experiencia:
        return []
    parts = re.split(r",|;|\.|\n|\s+y\s+|\s+e\s+|\s+-\s+|\|", experiencia)
    candidates, seen = [], set()
    for part in parts:
        part = part.strip().rstrip(".,;:")
        if not part or len(part) > 80:
            continue
        for match in _NAME_PATTERN.finditer(part):
            name = match.group(1).strip()
            words = name.split()
            while words and words[0].lower() in _LEADING_NOISE:
                words = words[1:]
            if not words:
                continue
            name = " ".join(words)
            key = name.lower()
            if key not in seen and len(name) >= 4 and key not in _STOPWORDS:
                seen.add(key)
                candidates.append(name)
                if len(candidates) >= max_results:
                    return candidates
    return candidates


def buscar_redes_sociales(aplicante: dict) -> dict:
    """
    Retorna:
    {
      "perfil": ["url", ...],           # redes sociales del candidato (nombre+ciudad exactos)
      "negocios": [                     # negocios declarados en experiencia
        {"nombre": "...", "urls": ["url", ...]}
      ]
    }
    """
    nombre = (aplicante.get("nombre") or "").strip()
    ciudad = (aplicante.get("ciudad") or "").strip()
    experiencia = aplicante.get("experiencia_gastronomica") or ""

    ciudad_ok = _ciudad_valida(ciudad)

    # ── 1. Perfiles personales (Instagram, TikTok, LinkedIn) ──────────────────
    perfil_urls = []
    if nombre and ciudad_ok:
        plataformas = [
            f'"{nombre}" "{ciudad}" site:instagram.com',
            f'"{nombre}" "{ciudad}" site:tiktok.com',
            f'"{nombre}" "{ciudad}" site:linkedin.com/in',
        ]

        def buscar_personal(query):
            hits = _ddg_search(query, max_results=2)
            return [
                h["url"] for h in hits
                if h["url"] and _match_nombre(h["texto"], nombre) and _match_ciudad(h["texto"], ciudad)
            ]

        with ThreadPoolExecutor(max_workers=3) as pool:
            for urls in pool.map(buscar_personal, plataformas):
                for u in urls:
                    if u not in perfil_urls:
                        perfil_urls.append(u)

    # ── 2. Negocios declarados ────────────────────────────────────────────────
    negocios_result = []
    negocios_declarados = _extract_business_names(experiencia)

    def buscar_negocio(negocio):
        ciudad_q = f' "{ciudad}"' if ciudad_ok else ""
        queries = [
            f'"{negocio}"{ciudad_q} site:instagram.com',
            f'"{negocio}"{ciudad_q} site:tiktok.com',
            f'"{negocio}"{ciudad_q}',           # sitio web / Facebook / reseñas
        ]

        def run(q):
            hits = _ddg_search(q, max_results=2)
            return [
                h["url"] for h in hits
                if h["url"] and _match_nombre(h["texto"], negocio)
            ]

        urls = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            for found in pool.map(run, queries):
                for u in found:
                    if u not in urls:
                        urls.append(u)

        return {"nombre": negocio, "urls": urls}

    if negocios_declarados:
        with ThreadPoolExecutor(max_workers=min(3, len(negocios_declarados))) as pool:
            negocios_result = [n for n in pool.map(buscar_negocio, negocios_declarados) if n["urls"]]

    return {"perfil": perfil_urls, "negocios": negocios_result}
