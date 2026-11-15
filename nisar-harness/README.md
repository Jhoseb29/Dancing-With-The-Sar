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

## Salidas para el globo (sin imágenes)

Por defecto el harness genera `tif`, `geojson`, `globe` y `objects`. Ya no produce PNG; si se necesitan, se piden con `--formats png rgb classes histogram kml`.

- `granules/<id>/formats/<id>_globe.json`: grilla lon/lat común a todas las tomas de la corrida (máx. 400 celdas por lado). Trae la clase de dispersión por celda y el brillo HH/HV cuantizado (`dB = -35 + v*0.2`). El navegador la colorea, así que las tomas se pueden alternar y comparar celda a celda.
- `granules/<id>/formats/<id>_objects.geojson`: la grilla de clases convertida en **objetos** (polígonos suavizados por mancha: lagunas, zonas urbanas, suelo desnudo o quemado, bosque) con área y brillo medio. El globo los dibuja apoyados sobre el relieve 3D, y las zonas urbanas grandes se levantan en 3D.
- `hotspots.geojson`: puntos de cambio entre la primera y la última toma, según el tema. El cambio es **relativo**: antes de aplicar umbrales se resta el corrimiento mediano de toda la escena (calibración o humedad general). El campo `summary` trae celdas, km² y % por tipo, y es lo único que recibe el modelo.
- Payload: la sección `globe` incluye `takes[]`, `hotspots`, `hotspots_summary` y los títulos de las capas.

## Elección de tomas

`lib/selection.py` decide qué gránulos se analizan:
- **Cobertura:** se elige la órbita (track + dirección) cuya huella CMR cubre mejor el área pedida.
- **Polarización:** se prefiere dual-pol (HH+HV).
- **Línea base:** con varias fechas se compara la más reciente con la más antigua de la ventana (por ejemplo, antes y después de la temporada de quemas).
- Los píxeles por debajo de −40 dB son relleno del borde del barrido y no entran al análisis.

## Sin Claude disponible

Si la suscripción no responde (por ejemplo, porque se alcanzó el límite de 5 h), la intención se resuelve con reglas: el tema por palabras clave y el lugar solo entre las regiones curadas. La parte de datos sigue funcionando y el payload sale como `data_only`.

## Integración con la UI

El frontend no ejecuta el harness: lo hace `backend/compute-py`, módulo `harness`.

| Endpoint | Qué hace |
|----------|----------|
| `POST /api/harness/ask` `{"text": "..."}` | Ejecuta `run.py --events -- "<texto>"` y devuelve un stream NDJSON con los eventos de progreso y un último evento `result` que trae el payload. |
| `GET /api/harness/runs/{run_id}` | Payload de una corrida ya hecha, sin re-ejecutarla. |
| `GET /api/harness/runs/{run_id}/files/{path}` | Imágenes y descargas de la corrida. Solo extensiones permitidas y sin salir de la carpeta de la corrida. |

En Angular, el chat `layout/harness-dock` permite preguntar por texto o por voz (Web Speech API del navegador). Al terminar, el resultado se abre en la vista **Análisis NISAR** (`/explicaciones`), que muestra:
- las tomas por fecha;
- las capas de clases, HH y HV;
- los puntos de cambio como mapa de calor;
- la celda bajo el clic;
- la lección.

`/explicaciones?run=<run_id>` abre una corrida ya hecha (enlace compartible).


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
