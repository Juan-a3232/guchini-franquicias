from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi import Body
from dotenv import load_dotenv
import json
import os
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

load_dotenv()

from scorer import evaluar_todos
from data_loader import load_candidates

app = FastAPI()

ESTADOS_FILE = "estados.json"
MAX_CANDIDATOS = int(os.environ.get("MAX_CANDIDATOS", "40"))


def get_aplicantes():
    """Carga candidatos desde Google Sheet (con fallback a mock_data.json)."""
    try:
        return load_candidates(top_n=MAX_CANDIDATOS)
    except Exception as e:
        print(f"[data_loader] Error cargando desde Google Sheets: {e}. Usando mock_data.json.")
        with open("mock_data.json", encoding="utf-8") as f:
            return json.load(f)


@app.on_event("startup")
async def startup_event():
    import asyncio
    asyncio.create_task(evaluar_en_background())

async def evaluar_en_background():
    import asyncio
    if not os.path.exists("resultados.json"):
        print("Evaluando aplicantes en background...")
        loop = asyncio.get_event_loop()
        aplicantes = await loop.run_in_executor(None, get_aplicantes)
        resultados = await loop.run_in_executor(None, evaluar_todos, aplicantes)
        with open("resultados.json", "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        print("Evaluación completa.")


def load_estados():
    if os.path.exists(ESTADOS_FILE):
        with open(ESTADOS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_estados(estados):
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


@app.get("/api/ranking")
def get_ranking():
    if os.path.exists("resultados.json"):
        with open("resultados.json", encoding="utf-8") as f:
            resultados = json.load(f)
        return merge_estados(resultados)

    aplicantes = get_aplicantes()
    resultados = evaluar_todos(aplicantes)

    with open("resultados.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    return merge_estados(resultados)


@app.post("/api/ranking/refresh")
def refresh_ranking():
    if os.path.exists("resultados.json"):
        os.remove("resultados.json")
    return get_ranking()


@app.post("/api/aplicante/{aplicante_id}/estado")
def update_estado(aplicante_id: int, body: dict = Body(...)):
    estados = load_estados()
    key = str(aplicante_id)
    if key not in estados:
        estados[key] = {}
    estados[key]["estado"] = body.get("estado", "Pendiente")
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
    if not os.path.exists("resultados.json"):
        return {"error": "No hay datos"}

    with open("resultados.json", encoding="utf-8") as f:
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


app.mount("/", StaticFiles(directory="static", html=True), name="static")
