# CLAUDE.md — alert-harness ("Centinela" en la web)

Sistema de alerta temprana por cuencas: **lluvia (NASA GPM IMERG) + relieve (Copernicus DEM) + evidencia radar (nisar-harness: NISAR o Sentinel-1)** → indicadores validados por JSON Schema → alerta por área → WebSocket → UI. Se evalúa contra casos reales y se mejora paso a paso.

## Piezas
| Pieza | Dónde |
|---|---|
| Fuentes (con caché en `output/cache/`) | `alerts/sources/imerg.py` (diaria), `imerg_hh.py` (media hora), `dem.py`, `radar.py` |
| Contexto de ciudad para la web: lluvia 24 h cada 30 min + próxima pasada de radar | `alerts/situation.py`, `alerts/radar_schedule.py` → `output/monitor/{rain,radar}.json` |
| Indicadores (cada uno pasa `schemas/indicator.schema.json`) | `alerts/indicators.py` |
| Motor determinista (índice, nivel, confianza, acciones) | `alerts/engine.py` + `config/thresholds.yaml` + `config/protocols.yaml` |
| Alerta (pasa `schemas/alert.schema.json`) | `run_alert.py` → `output/alerts/*.json` |
| Monitor automático (histéresis) + vista compacta para la UI (señales 0..1, sin texto) | `alerts/monitor.py`, `alerts/summary.py` → `output/monitor/state.json` |
| Distritos y cuencas como vectores (reconstruidos del WMS del GAMC) + terreno (Melton) + sedimento radar | `alerts/districts.py`, `alerts/basins.py` → `data/*.geojson` |
| WebSocket a la UI | `backend/compute-py/src/modules/alerts` (`/api/alerts/ws`) |
| Casos de evaluación (pasan `schemas/case.schema.json`) | `cases/*.json` |
| Evaluación y puntaje | `run_eval.py` → `output/evals/<ts>/scorecard.{md,json}` + `output/evals/history.jsonl` |
| Comunicación (modelo) | skill `alert-advisor` (no decide nivel ni acciones) |

## Protocolo de mejora (obligatorio)
1. Lee el último `scorecard.md`: qué casos fallan y qué expectativas no se cumplen.
2. Formula **una** hipótesis física (p. ej. "la lluvia de una mazamorra cae aguas arriba: ampliar la cuenca de aporte").
3. Cambia **una sola cosa** (un umbral en `thresholds.yaml` con su fuente, un indicador, una fuente, una regla).
4. `uv run python run_eval.py --nota "<qué cambiaste y por qué>"`.
5. Conserva el cambio solo si el puntaje sube **sin** aumentar las falsas alarmas; si no, reviértelo y anótalo.
6. Nunca ajustes umbrales para que un caso concreto pase sin una razón física: sobreajuste con pocos casos.
7. Agregar casos (eventos reales con fuente + días sin evento) siempre vale más que afinar umbrales.

## Hipótesis rechazadas (no repetir sin datos nuevos)
- v4, pico IMERG por media hora: no separa eventos de días lluviosos sin daño (ver comentario en `thresholds.yaml`).

## Reglas
- Todo número sale de código determinista; el modelo solo redacta.
- Cada parámetro en YAML lleva su fuente o la marca "supuesto inicial".
- El índice de riesgo **no es probabilidad**; la confianza dice qué faltó ver.
- Los textos que ve la ciudadanía viven en el frontend (i18n), cortos y sin jerga; el harness entrega números y categorías.
- No pidas la lluvia del día a SENAMHI: no hay acceso digital abierto (ver documentación del proyecto).
