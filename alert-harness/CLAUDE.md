# CLAUDE.md — alert-harness

Sistema de alerta temprana por cuencas: **lluvia (NASA GPM IMERG) + relieve (Copernicus DEM) + evidencia radar (nisar-harness: NISAR o Sentinel-1)** → indicadores validados por JSON Schema → alerta por área → WebSocket → UI. Se evalúa contra casos reales y se mejora paso a paso.

## Piezas
| Pieza | Dónde |
|---|---|
| Fuentes (con caché en `output/cache/`) | `alerts/sources/imerg.py`, `dem.py`, `radar.py` |
| Indicadores (cada uno pasa `schemas/indicator.schema.json`) | `alerts/indicators.py` |
| Motor determinista (índice, nivel, confianza, acciones) | `alerts/engine.py` + `config/thresholds.yaml` + `config/protocols.yaml` |
| Alerta (pasa `schemas/alert.schema.json`) | `run_alert.py` → `output/alerts/*.json` |
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

## Reglas
- Todo número sale de código determinista; el modelo solo redacta.
- Cada parámetro en YAML lleva su fuente o la marca "supuesto inicial".
- El índice de riesgo **no es probabilidad**; la confianza dice qué faltó ver.
- No pidas la lluvia del día a SENAMHI: no hay acceso digital abierto (ver documentación del proyecto).
