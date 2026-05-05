# Guchini Franquicias — Panel de Evaluación

## Qué es
Dashboard web para que el equipo de Guchini (sandwichería viral de Mendoza, Argentina)
evalúe y gestione candidatos a franquiciados. Los candidatos completan un Google Form;
el sistema los puntúa automáticamente con IA y los muestra en un ranking interactivo.

## Stack
- **Backend:** FastAPI (Python), sin Node ni npm
- **Frontend:** HTML/CSS/JS estático (carpeta `static/`)
- **IA:** Anthropic API — modelo `claude-haiku-4-5`
- **Búsqueda pública:** `ddgs` (DuckDuckGo, sin API key)
- **Hosting:** Railway (Europe West 4)
- **Storage persistente:** Railway Volume montado en `/data` via env var `DATA_DIR`
- **Excel export:** `openpyxl`
- **Datos de candidatos:** Google Sheets (via `data_loader.py`)

## Archivos principales
| Archivo | Rol |
|---|---|
| `main.py` | FastAPI app, endpoints, background tasks, cache logic |
| `scorer.py` | Evaluación con Claude Haiku, JSON parsing, semaphore, sort |
| `enricher.py` | Búsqueda pública en DDG por candidato y por negocio declarado |
| `data_loader.py` | Lee candidatos desde Google Sheets |
| `static/index.html` | UI completa (ranking, pipeline, filtros, export) |
| `mock_data.json` | Datos de prueba locales |

## Archivos persistentes (Railway Volume)
- `$DATA_DIR/resultados.json` — evaluaciones cacheadas, ordenadas por score
- `$DATA_DIR/estados.json` — estados manuales (Pendiente/Contactado/etc.) y notas por candidato

## Cómo funciona la evaluación
1. `data_loader.py` carga candidatos desde Google Sheets, asigna `id` numérico por posición
2. `enricher.py` busca en DDG: perfil público del candidato + cada negocio declarado (hasta 4)
3. `scorer.py` arma el prompt con criterios Guchini + datos del candidato + enrichment, llama a Haiku
4. Resultado: JSON con `score` (1–10), `breakdown`, `resumen`, `fortalezas`, `red_flags`, `recomendacion`
5. Se guarda en `resultados.json`, ordenado por score desc

## Criterios de evaluación (pesos)
- Capacidad financiera: 30% (mínimo viable USD 70K, ideal USD 105K+)
- Perfil comercial y liderazgo: 25%
- Disponibilidad operativa: 20% (inversor pasivo = penalización fuerte)
- Motivación y fit con la marca: 15%
- Ciudad y mercado: 10%

## Smart cache (sistema incremental)
- `_ids_in_cache()` retorna IDs con evaluación real (excluye FALLBACKs)
- `_is_fallback(r)` detecta evaluaciones fallidas por `"Error en evaluación automática"` en `red_flags`
- "Actualizar evaluación" solo evalúa candidatos nuevos + FALLBACKs — nunca re-evalúa los buenos
- "Re-evaluar todo" está **oculto** en la UI (`display:none`). Contraseña: `guchini2025`. Usar solo si se cambian los criterios de evaluación. Cuesta ~$15 y tarda ~20 min para 683 candidatos.

## Endpoints principales
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/ranking` | Lista todos los resultados con estados fusionados |
| GET | `/api/ranking/status` | Progreso de evaluación en curso |
| POST | `/api/ranking/refresh` | Evaluación incremental (solo nuevos + FALLBACKs) |
| POST | `/api/ranking/refresh-full` | Re-evaluación completa (oculto en UI) |
| POST | `/api/aplicante/{id}/estado` | Actualiza estado manual |
| POST | `/api/aplicante/{id}/nota` | Actualiza nota manual |
| GET | `/api/export/csv` | Descarga Excel formateado |

## Concurrencia y límites
- `asyncio.Semaphore(2)` en scorer — máximo 2 candidatos en paralelo con Anthropic
- `ThreadPoolExecutor` en enricher — búsquedas DDG corren en threads para no bloquear asyncio
- Guardado incremental cada 10 candidatos evaluados
- Deduplicación por ID en el save final (keep last = más reciente)

## Variables de entorno requeridas
```
ANTHROPIC_API_KEY=...
DATA_DIR=/data            # Railway Volume mount point
```

## Deploy
- Railway detecta el repo GitHub automáticamente
- Cada push a `master` dispara un redeploy
- El Volume (`guchini-franquicias-volume`) persiste `resultados.json` y `estados.json` entre deploys

## Pendientes
- Email automático de bienvenida al completar el form (necesita credenciales Gmail de Federico)
- Email de aprobación con link de Google Calendar (ídem)
- Agregar campos al Google Form: Instagram/web, LinkedIn, slots estructurados de negocios anteriores
