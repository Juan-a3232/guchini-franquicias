from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi import Body
from dotenv import load_dotenv
import asyncio
import json
import os
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

load_dotenv()

from scorer import evaluar_todos_async, _safe_score
from data_loader import load_candidates
from mailer import mail_bienvenida, mail_convocatoria, WELCOME_CUTOFF_ID

GMAIL_FROM = os.environ.get("GMAIL_FROM", "franquicias@guchini.com.ar")

app = FastAPI()

# ─── Persistent storage paths ─────────────────────────────────────────────────
# DATA_DIR apunta al Railway Volume si está configurado, sino usa directorio actual.
# Esto hace que resultados.json y estados.json sobrevivan a los deploys.
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

RESULTADOS_FILE = os.path.join(DATA_DIR, "resultados.json")
ESTADOS_FILE    = os.path.join(DATA_DIR, "estados.json")

# ─── Evaluation progress state ────────────────────────────────────────────────
eval_status = {
    "running": False,
    "done": 0,
    "total": 0,
    "error": None,
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_aplicantes():
    """Carga candidatos desde Google Sheet (con fallback a mock_data.json)."""
    try:
        return load_candidates()   # all candidates, sorted by pre-score
    except Exception as e:
        print(f"[data_loader] Error cargando desde Google Sheets: {e}. Usando mock_data.json.")
        with open("mock_data.json", encoding="utf-8") as f:
            return json.load(f)


def load_estados():
    if os.path.exists(ESTADOS_FILE):
        with open(ESTADOS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_estados(estados: dict):
    with open(ESTADOS_FILE, "w", encoding="utf-8") as f:
        json.dump(estados, f, ensure_ascii=False, indent=2)


def merge_estados(resultados):
    estados = load_estados()
    for r in resultados:
        key = str(r["id"])
        if key in estados:
            r["estado"] = estados[key].get("estado", "Pendiente")
            r["nota"] = estados[key].get("nota", "")
        else:
            r["estado"] = "Pendiente"
            r["nota"] = ""
    return resultados


# ─── Smart-cache helpers ───────────────────────────────────────────────────────

def _is_fallback(r: dict) -> bool:
    """Returns True if this result is a failed/fallback evaluation that should be retried."""
    flags = r.get("evaluacion", {}).get("red_flags", [])
    return "Error en evaluación automática" in flags


def _ids_in_cache() -> set:
    """Returns the set of IDs that already have a REAL result in resultados.json.
    FALLBACKs are excluded so they get re-evaluated on the next refresh."""
    if not os.path.exists(RESULTADOS_FILE):
        return set()
    with open(RESULTADOS_FILE, encoding="utf-8") as f:
        cached = json.load(f)
    return {r.get("id") for r in cached if r.get("id") is not None and not _is_fallback(r)}


def _load_cache() -> list:
    if not os.path.exists(RESULTADOS_FILE):
        return []
    with open(RESULTADOS_FILE, encoding="utf-8") as f:
        return json.load(f)


# ─── Background evaluation task ───────────────────────────────────────────────

async def run_evaluation_task(aplicantes_nuevos: list, cached_resultados: list):
    """
    Evaluates only the new applicants (not already in cache) and merges results.
    Saves incrementally so partial results are never lost if interrupted.
    """
    global eval_status
    eval_status["running"] = True
    eval_status["done"] = 0
    eval_status["total"] = len(aplicantes_nuevos)
    eval_status["error"] = None

    nuevos_resultados = list(cached_resultados)  # start with cached

    def on_progress(resultado):
        eval_status["done"] += 1
        nuevos_resultados.append(resultado)
        # Save incrementally after every 10 candidates
        if eval_status["done"] % 10 == 0 or eval_status["done"] == eval_status["total"]:
            sorted_resultados = sorted(nuevos_resultados, key=_safe_score, reverse=True)
            with open(RESULTADOS_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted_resultados, f, ensure_ascii=False, indent=2)

    try:
        await evaluar_todos_async(aplicantes_nuevos, on_progress=on_progress)

        # Final save: deduplicate by ID (keep last = freshly evaluated), then sort
        seen_ids: set = set()
        deduped = []
        for r in reversed(nuevos_resultados):
            rid = r.get("id")
            if rid not in seen_ids:
                seen_ids.add(rid)
                deduped.append(r)
        all_resultados = sorted(deduped, key=_safe_score, reverse=True)
        with open(RESULTADOS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_resultados, f, ensure_ascii=False, indent=2)

        print(f"[scorer] Evaluación completa: {eval_status['done']} nuevos + {len(cached_resultados)} en caché = {len(all_resultados)} total")
    except Exception as e:
        eval_status["error"] = str(e)
        print(f"[scorer] Error en evaluación: {e}")
    finally:
        eval_status["running"] = False


# ─── Bienvenida loop ──────────────────────────────────────────────────────────

async def bienvenida_loop():
    """
    Cada 5 minutos chequea si hay candidatos nuevos (ID > WELCOME_CUTOFF_ID)
    que no hayan recibido el mail de bienvenida, y se los manda.
    """
    if not GMAIL_FROM:
        print("[mailer] GMAIL_FROM no configurado — loop de bienvenida desactivado.")
        return

    print(f"[mailer] Loop de bienvenida activo (cutoff ID={WELCOME_CUTOFF_ID}, cada 5 min).")
    while True:
        await asyncio.sleep(300)  # 5 minutos
        try:
            loop = asyncio.get_event_loop()
            aplicantes = await loop.run_in_executor(None, get_aplicantes)
            estados = load_estados()
            guardado = False

            for a in aplicantes:
                aid = a.get("id", 0)
                if aid <= WELCOME_CUTOFF_ID:
                    continue  # candidato anterior al corte
                key = str(aid)
                if estados.get(key, {}).get("bienvenida_enviada"):
                    continue  # ya recibió el mail

                email  = (a.get("email") or "").strip()
                nombre = (a.get("nombre") or "").strip()
                if not email or not nombre:
                    continue

                ok = mail_bienvenida(nombre, email)
                if ok:
                    if key not in estados:
                        estados[key] = {}
                    estados[key]["bienvenida_enviada"] = True
                    guardado = True

            if guardado:
                save_estados(estados)

        except Exception as e:
            print(f"[mailer] Error en bienvenida_loop: {e}")


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    if os.path.exists(RESULTADOS_FILE):
        print(f"[startup] Cargando resultados existentes desde {RESULTADOS_FILE}")
    else:
        print(f"[startup] Sin datos en {RESULTADOS_FILE} — esperando evaluación manual.")
    asyncio.create_task(bienvenida_loop())


# ─── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/ranking/status")
def get_eval_status():
    return {
        "running": eval_status["running"],
        "done": eval_status["done"],
        "total": eval_status["total"],
        "error": eval_status["error"],
    }


@app.get("/api/ranking")
def get_ranking():
    if os.path.exists(RESULTADOS_FILE):
        with open(RESULTADOS_FILE, encoding="utf-8") as f:
            resultados = json.load(f)
        return merge_estados(resultados)
    return []


@app.post("/api/ranking/refresh")
async def refresh_ranking():
    """
    Kicks off a background re-evaluation.
    Only evaluates candidates whose email isn't in the current cache.
    Returns immediately with status info.
    """
    global eval_status

    if eval_status["running"]:
        return {"status": "already_running", "done": eval_status["done"], "total": eval_status["total"]}

    loop = asyncio.get_event_loop()
    aplicantes = await loop.run_in_executor(None, get_aplicantes)
    # Exclude FALLBACKs from the starting cache — they will be re-evaluated
    cached_resultados = [r for r in _load_cache() if not _is_fallback(r)]

    cached_ids = _ids_in_cache()
    aplicantes_nuevos = [
        a for a in aplicantes
        if a.get("id") not in cached_ids
    ]

    if not aplicantes_nuevos:
        # Nothing new — return cached results immediately
        with open(RESULTADOS_FILE, encoding="utf-8") as f:
            resultados = json.load(f)
        return {"status": "no_new_candidates", "total_cached": len(resultados)}

    print(f"[refresh] {len(aplicantes_nuevos)} nuevos candidatos a evaluar (ya en caché: {len(cached_resultados)})")
    asyncio.create_task(run_evaluation_task(aplicantes_nuevos, cached_resultados))

    return {
        "status": "started",
        "new": len(aplicantes_nuevos),
        "cached": len(cached_resultados),
    }


@app.post("/api/ranking/refresh-full")
async def refresh_full_ranking():
    """Forces a full re-evaluation of ALL candidates (ignores cache)."""
    global eval_status

    if eval_status["running"]:
        return {"status": "already_running"}

    if os.path.exists(RESULTADOS_FILE):
        os.remove(RESULTADOS_FILE)

    loop = asyncio.get_event_loop()
    aplicantes = await loop.run_in_executor(None, get_aplicantes)
    asyncio.create_task(run_evaluation_task(aplicantes, []))

    return {"status": "started", "total": len(aplicantes)}


@app.post("/api/aplicante/{aplicante_id}/estado")
def update_estado(aplicante_id: int, body: dict = Body(...)):
    estados = load_estados()
    key = str(aplicante_id)
    if key not in estados:
        estados[key] = {}

    nuevo_estado   = body.get("estado", "Pendiente")
    estado_anterior = estados[key].get("estado", "Pendiente")
    estados[key]["estado"] = nuevo_estado
    save_estados(estados)

    # MAIL 2 — se manda cuando Federico aprieta "Aprobar" (estado → Contactado)
    # Solo se manda una vez por candidato.
    if nuevo_estado == "Contactado" and estado_anterior != "Contactado" \
            and not estados[key].get("convocatoria_enviada"):
        if os.path.exists(RESULTADOS_FILE):
            with open(RESULTADOS_FILE, encoding="utf-8") as f:
                resultados = json.load(f)
            candidato = next((r for r in resultados if r.get("id") == aplicante_id), None)
            if candidato:
                email  = (candidato.get("email") or "").strip()
                nombre = (candidato.get("nombre") or "").strip()
                if email and nombre:
                    ok = mail_convocatoria(nombre, email)
                    if ok:
                        estados[key]["convocatoria_enviada"] = True
                        save_estados(estados)

    return {"ok": True}


@app.post("/api/aplicante/{aplicante_id}/nota")
def update_nota(aplicante_id: int, body: dict = Body(...)):
    estados = load_estados()
    key = str(aplicante_id)
    if key not in estados:
        estados[key] = {}
    estados[key]["nota"] = body.get("nota", "")
    save_estados(estados)
    return {"ok": True}


@app.get("/api/export/csv")
def export_excel():
    if not os.path.exists(RESULTADOS_FILE):
        return {"error": "No hay datos"}

    with open(RESULTADOS_FILE, encoding="utf-8") as f:
        resultados = json.load(f)
    resultados = merge_estados(resultados)

    BLACK = "1A1A1A"
    WHITE = "FFFFFF"
    GREEN = "16A34A"
    AMBER = "D97706"
    RED = "DC2626"
    GRAY = "F5F5F0"

    def fill(hex): return PatternFill("solid", start_color=hex, fgColor=hex)
    def thin_border():
        s = Side(style="thin", color="DDDDDD")
        return Border(left=s, right=s, top=s, bottom=s)

    wb = Workbook()
    ws = wb.active
    ws.title = "Ranking Franquicias"

    ws.merge_cells("A1:M1")
    ws["A1"] = "GUCHINI · RANKING DE FRANQUICIAS"
    ws["A1"].font = Font(bold=True, color=WHITE, name="Calibri", size=16)
    ws["A1"].fill = fill(BLACK)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:M2")
    from datetime import datetime
    ws["A2"] = datetime.now().strftime("%B %Y")
    ws["A2"].font = Font(color="AAAAAA", name="Calibri", size=10)
    ws["A2"].fill = fill(BLACK)
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 8

    headers = ["#", "Nombre", "Ciudad", "Score", "Recomendación", "Capital (USD)", "Local Propio", "Disponibilidad", "Estado", "Email", "Fortalezas", "Red Flags", "Notas"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = Font(bold=True, color=WHITE, name="Calibri", size=10)
        cell.fill = fill(BLACK)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border()
    ws.row_dimensions[4].height = 28

    rec_colors = {"APROBAR": (GREEN, "DCFCE7"), "REVISAR": (AMBER, "FEF9C3"), "RECHAZAR": (RED, "FEE2E2")}

    for i, r in enumerate(resultados):
        e = r["evaluacion"]
        excel_row = i + 5
        row_bg = GRAY if i % 2 == 0 else WHITE
        rec = e["recomendacion"]

        row_data = [
            i + 1,
            r["nombre"],
            r["ciudad"],
            e["score"],
            rec,
            r.get("capital_disponible", ""),
            "Sí" if r.get("tiene_local") else "No",
            r.get("disponibilidad", ""),
            r.get("estado", "Pendiente"),
            r.get("email", ""),
            " | ".join(e.get("fortalezas", [])),
            " | ".join(e.get("red_flags", [])),
            r.get("nota", "")
        ]

        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=excel_row, column=col, value=val)
            cell.border = thin_border()
            cell.fill = fill(row_bg)
            cell.font = Font(color=BLACK, name="Calibri", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            if col == 1:
                cell.font = Font(bold=True, color=BLACK, name="Calibri", size=11)
            elif col == 4:
                cell.font = Font(bold=True, color=BLACK, name="Calibri", size=11)
            elif col == 5:
                bg, _ = rec_colors.get(rec, (BLACK, WHITE))
                cell.fill = fill(bg)
                cell.font = Font(bold=True, color=WHITE, name="Calibri", size=10)
            elif col == 6:
                cell.number_format = '$#,##0'
            elif col in [11, 12, 13]:
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        ws.row_dimensions[excel_row].height = 40

    col_widths = [5, 22, 24, 8, 14, 14, 12, 14, 14, 30, 50, 40, 25]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A5"

    summary_row = len(resultados) + 6
    aprobados  = sum(1 for r in resultados if r["evaluacion"]["recomendacion"] == "APROBAR")
    revisados  = sum(1 for r in resultados if r["evaluacion"]["recomendacion"] == "REVISAR")
    rechazados = sum(1 for r in resultados if r["evaluacion"]["recomendacion"] == "RECHAZAR")
    ws.merge_cells(f"A{summary_row}:M{summary_row}")
    ws[f"A{summary_row}"] = f"Total: {len(resultados)}  |  Aprobar: {aprobados}  |  Revisar: {revisados}  |  Rechazar: {rechazados}"
    ws[f"A{summary_row}"].font = Font(bold=True, color=WHITE, name="Calibri", size=10)
    ws[f"A{summary_row}"].fill = fill(BLACK)
    ws[f"A{summary_row}"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[summary_row].height = 24

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        iter([output.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ranking_guchini.xlsx"}
    )


@app.get("/api/test-mail")
def test_mail(to: str):
    """Endpoint temporal para probar el envío de mails."""
    from mailer import send_email
    ok, error = send_email(to, "Test mail · Guchini Franquicias", f"Este es un mail de prueba. Si llegó, el sistema funciona correctamente.")
    return {"ok": ok, "error": error, "from": GMAIL_FROM, "to": to}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
