# NISAR Unified Harness

Haces una pregunta en lenguaje natural y el harness responde con datos radar **NISAR L2 GCOV** (banda L) leídos directamente de AWS. No hay que saber nada de `.h5`, bbox ni colecciones.

```bash
uv run python run.py "¿Hubo incendios recientes en la Chiquitania?"
uv run python run.py "¿Cómo están las lagunas de la cuenca de Cochabamba?"
uv run python run.py "inundaciones en el río Rocha en febrero" --events   # progreso en JSON lines
```

Diagrama completo en [flow.md](flow.md).

## Qué es determinista y qué no

| Paso | Quién | Costo |
|------|-------|-------|
| Entender la pregunta (lugar, área, tema, fechas) | Claude Haiku, 1 turno sin tools + validación en Python | ~3 s, ~500 tokens |
| Catálogo, streaming AWS, mapas, métricas, cambios entre fechas | Python | 0 tokens |
| Explicación (chat corto + lección) | Claude Sonnet, 1 turno sin tools, sin imágenes | ~2k tokens de entrada |

Las llamadas usan la **suscripción de Claude Code** (`claude -p`), no API key. Para gastar pocos tokens, `--system-prompt` reemplaza el prompt por defecto, `--tools ""` evita el bucle de agente y `--json-schema` exige salida estructurada.

## Temas (`lib/themes.py`)

| Tema | Ventana por defecto | Fechas | Qué busca el radar |
|------|---------------------|--------|--------------------|
| `incendios` | 90 días | 2 | Caída de HV/RVI (pérdida de biomasa) |
| `inundacion` | 60 días | 2 | Aumento de agua (reflexión especular) |
| `cuenca_hidrica` | 365 días | 3 | Extensión de agua y humedad del suelo |
| `vegetacion` | 365 días | 2 | Dispersión volumétrica |
| `urbano` | 365 días | 2 | Rebote doble |
| `general` | 120 días | 1 | Composición general |

## Integración con la UI

- **Entrada**: `run.py "<texto>"` o `run.py --request req.json` con `{"text": "..."}`. Cualquier campo de `PipelineRequest` (`lib/pipeline.py`) sobrescribe lo que se entendió del texto.
- **Progreso**: con `--events`, cada línea de stdout es un evento JSON (`stage`, `message`, `progress` 0–1); los logs van a stderr. También quedan en `events.jsonl`.
- **Resultado** `interpretacion_didactica_nisar.json`:
  - `chat`: `message` para la burbuja, `alert_level`, `highlights`, `follow_up_questions`.
  - `lesson_markdown`: lección "Aprende más" para mostrar debajo, dentro del mismo chat.
  - `media`: imágenes y descargas con `title`, `caption` y, en las capas de mapa, `bounds_lonlat`.
  - `metrics`, `time_series`, `change`: datos para tarjetas y gráficos.
  - `status`:
    - `complete`: datos y explicación del modelo listos.
    - `data_only`: hay datos y mapas, pero sin explicación del modelo.
    - `needs_clarification` o `no_data`: no hubo análisis; `chat.message` lleva la pregunta o el aviso para el usuario.

## Configuración (`.env`)

| Variable | Uso | Default |
|----------|-----|---------|
| `EARTHDATA_TOKEN` | Streaming HTTPS desde ASF/AWS | — |
| `NISAR_AWS_CREDENTIALS` | JSON STS temporal (S3 directo, solo in-region us-west-2) | `../aws-nisar-data-credentials.json` |
| `NISAR_OUTPUT_DIR` | Carpeta de corridas | `./output` |
| `CLAUDE_INTENT_MODEL` / `CLAUDE_INTERPRET_MODEL` | Modelos | `haiku` / `sonnet` |
| `CLAUDE_BIN`, `CLAUDE_TIMEOUT_S` | CLI de Claude Code | `claude`, `300` |

## Pasos individuales (sobre `output/latest` o `--run-dir`)

```bash
uv run python scripts/input_data.py "incendios en la Chiquitania"   # 0+1 intención + catálogo
uv run python scripts/export_nisar_formats.py                       # 2 mapas
uv run python scripts/curate_sar_physics.py                         # 3 métricas
uv run python scripts/interpret.py                                  # 4 explicación (re-ejecutable, barato)
```

## Salidas

Cada corrida queda en `output/runs/<YYYYMMDD_HHMMSS>/` y `output/latest` apunta a la última. `output/` no se versiona. La estructura está en [CLAUDE.md](CLAUDE.md).
