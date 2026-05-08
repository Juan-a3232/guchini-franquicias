"""
enricher.py — Búsqueda de perfiles en redes sociales.
Solo retorna URLs si el resultado contiene EXACTAMENTE el nombre y la ciudad del candidato.
No influye en el score — solo se usa para mostrar links en la tarjeta.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from ddgs import DDGS

_DDG_REGION = "ar-es"

# Ciudades que no son válidas para buscar (form default / internacional)
_CIUDADES_INVALIDAS = {
    "si es otro lugar",
    "internacional",
    "otra",
    "sin especificar",
}


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


def _match_exacto(texto: str, nombre: str, ciudad: str) -> bool:
    """Verdadero solo si AMBOS el nombre completo y la ciudad aparecen en el texto."""
    t = texto.lower()
    # Requiere las dos palabras del nombre (no solo una parte)
    partes_nombre = nombre.lower().split()
    nombre_ok = all(p in t for p in partes_nombre) if len(partes_nombre) >= 2 else nombre.lower() in t
    ciudad_ok = ciudad.lower() in t
    return nombre_ok and ciudad_ok


def buscar_redes_sociales(aplicante: dict) -> dict:
    """
    Busca al candidato en Instagram, TikTok y LinkedIn.
    Solo incluye un URL si el resultado contiene exactamente su nombre Y su ciudad.
    """
    nombre = (aplicante.get("nombre") or "").strip()
    ciudad = (aplicante.get("ciudad") or "").strip()

    if not nombre or not _ciudad_valida(ciudad):
        return {"fuentes": []}

    plataformas = [
        ("instagram.com",    f'"{nombre}" "{ciudad}" site:instagram.com'),
        ("tiktok.com",       f'"{nombre}" "{ciudad}" site:tiktok.com'),
        ("linkedin.com/in",  f'"{nombre}" "{ciudad}" site:linkedin.com/in'),
    ]

    def buscar(plat_query):
        _, query = plat_query
        hits = _ddg_search(query, max_results=3)
        urls = []
        for h in hits:
            if h["url"] and _match_exacto(h["texto"], nombre, ciudad):
                urls.append(h["url"])
        return urls

    fuentes = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for urls in pool.map(buscar, plataformas):
            for url in urls:
                if url not in fuentes:
                    fuentes.append(url)

    return {"fuentes": fuentes}
