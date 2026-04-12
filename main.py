from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi import Body
from dotenv import load_dotenv
import json
import os
import csv
import io

load_dotenv()

from scorer import evaluar_todos

app = FastAPI()

ESTADOS_FILE = "estados.json"


@app.on_event("startup")
async def startup_event():
    import asyncio
    asyncio.create_task(evaluar_en_background())

async def evaluar_en_background():
    import asyncio
    if not os.path.exists("resultados.json"):
        print("Evaluando aplicantes en background...")
        loop = asyncio.get_event_loop()
        with open("mock_data.json", encoding="utf-8") as f:
            aplicantes = json.load(f)
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

    with open("mock_data.json", encoding="utf-8") as f:
        aplicantes = json.load(f)

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
def export_csv():
    if not os.path.exists("resultados.json"):
        return {"error": "No hay datos"}

    with open("resultados.json", encoding="utf-8") as f:
        resultados = json.load(f)

    resultados = merge_estados(resultados)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Nombre", "Ciudad", "Score", "Recomendacion", "Capital USD", "Local Propio", "Disponibilidad", "Estado", "Email", "Fortalezas", "Red Flags", "Nota"])

    for i, r in enumerate(resultados, 1):
        e = r["evaluacion"]
        writer.writerow([
            i,
            r["nombre"],
            r["ciudad"],
            e["score"],
            e["recomendacion"],
            r.get("capital_disponible", ""),
            "Sí" if r.get("tiene_local") else "No",
            r.get("disponibilidad", ""),
            r.get("estado", "Pendiente"),
            r.get("email", ""),
            " | ".join(e.get("fortalezas", [])),
            " | ".join(e.get("red_flags", [])),
            r.get("nota", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ranking_franquicias.csv"}
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")
