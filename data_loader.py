"""
data_loader.py
Lee candidatos reales desde el Google Sheet del formulario de franquicias Guchini.
Pre-filtra y ordena por score de pre-screening antes de pasarlos al scorer de IA.
"""
import requests
import csv
import io
from datetime import datetime

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/12LhhYdcaN6Q46sd71ehukzWhpvpV0bhP-OO3PRaepgI"
    "/export?format=csv&gid=692378162"
)

# Mapa capital: detectar el valor numérico desde el texto del formulario
CAPITAL_MAP = [
    (180000, ["180.000", "180,000"]),
    (150000, ["150.000", "150,000"]),
    (130000, ["130.000", "130,000"]),
    (100000, ["100.000", "100,000"]),
    (80000,  ["80.000",  "80,000"]),
]

# Ciudades prioritarias Año 1 (según Resumen Ejecutivo Guchini)
PRIORITY_CITIES = {"córdoba", "caba", "mar del plata", "bahía blanca", "bahia blanca"}
# Ciudades ya cubiertas por Casa Central (no priorizar)
COVERED_CITIES = {"mendoza", "san rafael", "san juan"}


def _get(row, idx):
    return row[idx].strip() if len(row) > idx else ""


def _parse_capital(raw):
    for amount, keywords in CAPITAL_MAP:
        for kw in keywords:
            if kw in raw:
                return amount
    return 0


def _parse_ciudad(raw):
    if not raw:
        return "Sin especificar"
    if "otro lugar" in raw.lower() or "enviar un correo" in raw.lower():
        return "Internacional / Otra"
    return raw.strip().rstrip(",").strip()


def _parse_operacion(raw):
    raw_l = raw.lower()
    if "gerencia" in raw_l or "otra persona" in raw_l or "otras personas" in raw_l:
        return "inversor"
    return "personal"


def _parse_fecha(raw):
    for fmt in ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return "2026-01-01"


def _pre_score(c, exp_raw):
    """
    Score rápido sin IA para ordenar candidatos antes de evaluación completa.
    Replica la lógica del scorer real pero sin llamadas a la API.
    """
    s = 0

    # Capital (30%)
    cap = c.get("capital_disponible", 0)
    if cap >= 150000:  s += 35
    elif cap >= 130000: s += 30
    elif cap >= 100000: s += 22
    elif cap >= 80000:  s += 12
    else:               s += 0

    # Perfil operativo (25%)
    if c.get("disponibilidad_operativa") == "personal":
        s += 25

    # Experiencia gastronómica (proxy del perfil comercial, 20%)
    if exp_raw.lower().startswith("si") or exp_raw.lower().startswith("sí"):
        s += 20

    # Ciudad prioritaria (10%)
    ciudad_l = c.get("ciudad", "").lower()
    if any(p in ciudad_l for p in PRIORITY_CITIES):
        s += 15
    elif not any(x in ciudad_l for x in COVERED_CITIES):
        s += 5  # potencial, al menos no cubierta

    # Disponibilidad inmediata (bonus)
    disp = c.get("disponibilidad", "").lower()
    if "inmediata" in disp:   s += 5
    elif "3 y 6" in disp:     s += 3

    return s


def load_candidates(top_n=None):
    """
    Descarga el Google Sheet, parsea todos los candidatos y los devuelve
    ordenados por pre-screening score (sin descartar ninguno).
    top_n: si se especifica, limita la cantidad retornada; None = todos.
    """
    r = requests.get(SHEET_URL, allow_redirects=True, timeout=30)
    r.raise_for_status()
    content = r.content.decode("utf-8")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    data_rows = rows[1:]  # skip header

    candidatos = []
    for i, row in enumerate(data_rows):
        nombre = _get(row, 5)
        if not nombre:
            continue

        exp_gastro_raw = _get(row, 10)
        exp_desc       = _get(row, 9)
        capital        = _parse_capital(_get(row, 14))
        ciudad         = _parse_ciudad(_get(row, 8))
        local_raw      = _get(row, 18)
        tiene_local    = "dispongo" in local_raw.lower()
        disp_op        = _parse_operacion(_get(row, 17))

        exp_text = (
            f"{'Sí' if exp_gastro_raw.lower().startswith('si') else 'No'} tiene experiencia gastronómica. "
            f"{exp_desc}"
        ).strip(" .")

        c = {
            "id": i + 1,
            "nombre": nombre,
            "email": _get(row, 7) or _get(row, 21),
            "ciudad": ciudad,
            "capital_disponible": capital,
            "capital_declarado": _get(row, 14),          # texto original del form
            "tiene_local": tiene_local,
            "disponibilidad_operativa": disp_op,
            "otras_fuentes_ingreso": _get(row, 19),
            "experiencia_gastronomica": exp_text,
            "por_que_guchini": _get(row, 12),
            "como_se_entero": _get(row, 11),
            "disponibilidad": _get(row, 13),
            "horas_dedicacion": _get(row, 16),
            "fecha_aplicacion": _parse_fecha(_get(row, 4)),
            "observaciones_internas": _get(row, 3),
        }

        c["_pre_score"] = _pre_score(c, exp_gastro_raw)
        candidatos.append(c)

    # Ordenar por pre-score descendente → los mejores primero
    candidatos.sort(key=lambda x: x["_pre_score"], reverse=True)

    # Tomar top_n si se especificó, sino todos
    top = candidatos[:top_n] if top_n is not None else candidatos

    # Limpiar campos internos antes de devolver
    for c in top:
        c.pop("_pre_score", None)

    print(f"[data_loader] {len(candidatos)} candidatos procesados → {len(top)} listos para evaluación")
    return top
