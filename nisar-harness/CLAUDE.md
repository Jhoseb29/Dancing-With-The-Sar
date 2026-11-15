# CLAUDE.md - Harness NISAR ("Dancing with the SARs")

Pregunta en lenguaje natural → datos radar **NISAR L2 GCOV** leídos directamente de AWS → mapas, métricas y una explicación didáctica para personas sin formación técnica.

## Capas

| Capa | Qué hace | Dónde |
|------|----------|-------|
| Intención (Claude Haiku, 1 turno) | Texto → lugar, bbox, tema y fechas; Python valida | `lib/intent.py`, `lib/prompts/intent_parser.md`, `lib/themes.py` |
| Determinista (Python/uv) | CMR → streaming S3/HTTPS → recorte AOI + multilook → formatos → métricas → cambios | `lib/` |
| Explicación (Claude Sonnet, 1 turno) | Contexto compacto → chat corto + lección | `lib/interpreter.py` + skill `nisar-didactic-interpreter` |

Todo número sale de Python. El modelo **no calcula, no descarga y no ve imágenes**: las imágenes se muestran al usuario, no se interpretan. No hay datos locales: todo se lee por streaming desde AWS.

## Corridas

`output/runs/<YYYYMMDD_HHMMSS>/` (`output/latest` apunta a la última); `output/` no se versiona.

```
run_manifest.json                     # request, intent, estado/duración/uso de tokens por paso
events.jsonl                          # progreso para la UI
query.json                            # catálogo CMR + estado STS/Earthdata
granules/<id>/curated_metrics.json    # métricas físicas
granules/<id>/formats.json            # índice de archivos exportados
granules/<id>/formats/                # GeoTIFF, GeoJSON, *_globe.json (grilla) y *_objects.geojson (objetos por clase); PNG/KML solo bajo pedido
hotspots.geojson                      # puntos de cambio entre tomas (relativos al corrimiento de la escena)
interpreter_context.json              # ENTRADA del modelo (~800 tokens)
interpretation_narrative.json         # SALIDA: mensaje corto de chat
interpretation.md                     # SALIDA: lección "Aprende más"
interpretacion_didactica_nisar.json   # payload final para Angular
```

## Al modificar el código

- `lib/` tiene la lógica (un módulo por responsabilidad). `scripts/` y `run.py` son CLIs delgados.
- Nuevo tema → entrada en `THEMES` (`lib/themes.py`) y en el enum del prompt de intención.
- Nueva región curada → `REGIONS` (`lib/regions.py`) con `aliases`.
- Nuevo formato → función en `lib/exporters.py` + `EXPORTERS` + `MEDIA_CATALOG` (`lib/interpreter.py`).
- El globo web no usa imágenes del harness: colorea `*_globe.json` en el navegador (`frontend/src/app/core/harness/globe-grid.ts`).
- Llamadas a Claude solo por `lib/claude_cli.py` (1 turno, sin tools, JSON schema).
- Configuración por variables de entorno (`lib/settings.py`).
- No ejecutes el pipeline completo para probar: tarda varios minutos y consume datos remotos. Prueba funciones puras (`intent.normalise`, `change.compare`) o `scripts/interpret.py --no-interpret` sobre una corrida existente.
