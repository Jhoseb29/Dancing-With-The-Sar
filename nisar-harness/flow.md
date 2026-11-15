```
Usuario (chat UI): "¿Hubo incendios recientes en la Chiquitania?"
       │   run.py "<texto>" --events     |   {"text": "..."} vía --request
       ▼
[Paso 0 · lib/intent.py]  Claude Haiku, 1 turno, sin tools, JSON schema   (~3 s, ~500 tokens)
       │  lugar + bbox + tema + fechas  →  validación determinista (rango, tamaño, región curada, fechas ≤ hoy)
       │  lib/themes.py: el tema decide ventana temporal, nº de fechas y métricas foco
       │  (sin lugar identificable → status needs_clarification + pregunta al usuario)
       ▼
[Paso 1 · lib/catalog.py]  NASA CMR (V1 > PROVISIONAL > BETA)  → query.json
       │  sin tomas NISAR suficientes / cobertura < 70 % → lib/catalog_sentinel1.py: Sentinel-1 OPERA RTC (bursts → pasadas)
       │  sin pasadas en la ventana → amplía a 12 meses (temporal_widened)
       │  selección: fecha más reciente + anteriores de la MISMA órbita (comparables)
       ▼
[lib/access.py + lib/scene.py]  streaming directo desde AWS (S3 STS → HTTPS range)
       │  solo los chunks del AOI · frecuencia por presupuesto · multilook (speckle)
       ├──────────────────────────────┐
       ▼                              ▼
[Paso 2 · lib/exporters.py]     [Paso 3 · lib/curation.py + sar_physics.py]
 granules/<id>/formats/ +        granules/<id>/curated_metrics.json
 formats.json                    (clases dual-pol, RVI, CPR, estación, región)
 (tif, geojson, *_globe.json:
  grilla lon/lat común, sin PNG)
       └──────────────┬───────────────┘
                      ▼
[Paso 3b · lib/hotspots.py]  cambio celda a celda (relativo al corrimiento de la escena) → hotspots.geojson
                      │
                      ▼
[Paso 4 · lib/change.py + lib/interpreter.py]
       │  interpreter_context.json  (~800 tokens: solo números + cambios ya calculados)
       │  Claude Sonnet, 1 turno, sin tools, rol = skill nisar-didactic-interpreter
       ▼
interpretation_narrative.json (chat corto)  +  interpretation.md (lección)
       ▼
interpretacion_didactica_nisar.json → UI: burbuja de chat · "Aprende más" (md)
       → vista Análisis NISAR: el navegador colorea *_globe.json por toma + hotspots como mapa de calor

Durante todo el proceso: events.jsonl / stdout --events  →  barra de progreso en la UI
```
