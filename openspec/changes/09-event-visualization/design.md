## Context

Fases 1–2 dejaron el shadow, la configuración en JSON y un agente Gemini que opera la UI por parches. Falta que el agente entienda **eventos** (incendios, inundaciones…) y muestre las imágenes correctas con fechas reales.

## Decisions

### D1. Categorías en `events.json`
| `id` | Satélites/capas (en orden de dibujo) | Lectura | Estadísticas |
| :--- | :--- | :--- | :--- |
| `wildfire` | VIIRS NOAA-20 falso color + focos FIRMS (VIIRS) | Rojizo/marrón = área quemada; puntos = focos detectados ese día | FIRMS |
| `flood` | VIIRS NOAA-20 falso color + MODIS Flood 2-Day | Celeste = agua, rojo = inundación, amarillo = recurrente, gris = sin datos (nubes); falso color: agua azul oscuro | — |
| `radar` | NISAR GCOV falso color | Colores = respuesta del radar banda L por polarización | — |
| `vegetation` | MODIS NDVI 16 días | Verde intenso = vegetación densa; marrón = suelo/seco | — |
| `deformation` | — (NISAR GUNW aún no procesado) | — | `available: false` |

El agente clasifica el pedido eligiendo un `event_type` de esta lista (enum generado desde el JSON); si no encaja, pregunta.

### D2. Capas `gibs-wmts` con tiempo
`url = https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{Time}/{tileMatrixSet}/{z}/{y}/{x}.{ext}`. El motor 2.5D reemplaza `{Time}` por `/time/date` y recrea la fuente al cambiar el día. Mapa base público, sin credenciales (excepción de `docs/03`).

### D3. Vista `events`
Motor 2.5D (MapLibre, proyección globo: sirve tanto para Bolivia como para Cochabamba). Panel con tipo de evento, lugar, rango, selector de día (±1 día, fecha), leyenda oficial, "cómo leer esta imagen", fuentes, y estadísticas FIRMS cuando aplica. Al elegir un día con picos, el agente puede saltar a esa fecha.

### D4. Shadow
- `/event`: `null` o `{ type, placeId, start, end }`.
- `/time/date`: día `YYYY-MM-DD` mostrado por las capas temporales.
- Validación: `type` en `events.json`, `placeId` en `places.json`, fechas ISO y `start ≤ date ≤ end` cuando hay evento.

### D5. FIRMS en backend (`modules/events`)
- Puerto `FireDataPort`; adaptador FIRMS `area` (CSV) en bloques de 5 días, concurrencia limitada, caché en `data/raw/firms/` (ignorado por git).
- Fuente por fecha según `data_availability`: SP (procesamiento estándar) donde exista, NRT para lo reciente.
- Filtro espacial: polígono de Bolivia (Natural Earth 1:50m, dominio público) para `bolivia`; bbox exacto para lugares de Cochabamba.
- `GET /api/events/fires/stats?place=&start=&end=` → `{ place, start, end, source, total, monthly[], peak_day, retrieved_at }` (rango máx. 2 años).
- `GET /api/events/fires?place=&date=` → GeoJSON de focos de ese día (`frp`, `confidence`, `acq_time`; sin datos personales).

### D6. Herramientas del agente
`show_event(event_type, place_id, start_date, end_date)`, `set_event_date(date)`, `get_fire_stats(place_id, start_date, end_date)`. El contexto de cada turno incluye la fecha de hoy.

## Risks / Trade-offs

- **[Riesgo] Cobertura irregular** (NISAR, DSWx-S1 por pasadas; nubes en MODIS) → la UI dice "sin cobertura en este día" y permite moverse de día; `events.json` guarda fechas con cobertura verificada.
- **[Riesgo] 2 años de FIRMS = ~146 peticiones por fuente** → caché en disco y límite de rango; primera consulta lenta (decenas de segundos), siguientes instantáneas.
- **[Trade-off] Sin focos en la vista 3D** en esta fase: el globo Cesium sigue mostrando la órbita; los eventos van en el motor 2.5D.

### Capas por vista (2026-11-14)
Las capas de un evento salen de `events.json` (no de `/layers`). `/layers` queda solo para las capas municipales GAMC de la cuenca, así cambiar de vista no borra lo que el usuario eligió en la otra.

### OPERA DSWx-S1 descartado para Cochabamba
Verificado con su colormap oficial: "no agua" es blanco opaco, "HAND masked" y "layover/shadow" son grises. En la cuenca (montaña) casi todo queda enmascarado y las escenas se ven como rectángulos. Se mantiene en `layers.json` por si sirve en llanuras (Beni), pero no en el evento `flood`.

### Fondo diario: VIIRS NOAA-20 en vez de MODIS Terra (2026-11-14)
La imagen diaria de MODIS Terra deja franjas negras entre órbitas cerca del ecuador (GIBS las rellena de negro en JPEG); se notaba al alejar el mapa (reporte del usuario). VIIRS NOAA-20 (`BandsM11-I2-I1`, equivalente al 7-2-1, y `TrueColor`) tiene una franja de ~3000 km y cubre el planeta sin huecos. Verificado: mismo día, MODIS con franjas y VIIRS sin ellas; datos desde 2018-01-05 (cubre la historia de FIRMS). Resolución algo menor (375 m frente a 250 m). Las capas MODIS siguen en el catálogo, sin uso en eventos.
