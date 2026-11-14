## Why

Fase 3 de la hoja de ruta del agente. El usuario debe poder pedir en lenguaje natural "¿hubo incendios en Bolivia los últimos 2 años?" o "muéstrame las inundaciones en Cochabamba" y que el agente **reconozca el tipo de evento**, lo **categorice** y muestre **las imágenes del satélite adecuado** para ese tipo (por ejemplo, agua en azul para inundaciones, cicatrices de quema para incendios), con cifras reales cuando existan.

## Fuentes verificadas (2026-11-14)

Verificadas leyendo el `WMTSCapabilities.xml` de NASA GIBS (EPSG:3857) y pidiendo teselas reales:

| Uso | Capa GIBS | Notas verificadas |
| :--- | :--- | :--- |
| Radar NISAR | `NISAR_L2_Geocoded_Polarimetric_Covariance` | Falso color GCOV, `GoogleMapsCompatible_Level13`, fechas 2025-10-29 → 2026-11-11 (cobertura por pasadas). Sobre el centro de Cochabamba hay imagen en **18 fechas** entre el 2026-06-25 y el 2026-10-25 (pares cada 12 días; hueco 2026-07-27 → 2026-08-10). El 2026-10-30 las pasadas caen al oeste y al este de la ciudad, no sobre ella. |
| Agua por radar | `OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1` | DSWx-S1, Level12. En catálogo, pero fuera del evento `flood` (ver design: tapa la cuenca de montaña). |
| Inundación | `MODIS_Combined_Flood_2-Day` | Diario, Level9, leyenda SVG oficial. |
| Falso color 7-2-1 | `MODIS_Terra_CorrectedReflectance_Bands721` | Diario, Level9: agua azul oscuro, vegetación verde, áreas quemadas rojizas. |
| Vegetación | `MODIS_Terra_L3_NDVI_16Day` | Compuesto de 16 días, Level9, leyenda SVG. |
| Color real | `MODIS_Terra_CorrectedReflectance_TrueColor` | Diario, Level9. |

Las capas de anomalías térmicas de GIBS en teselas vectoriales (`*_Thermal_Anomalies_*`) respondieron **404** en todas las pruebas: no se usan. Los focos de calor salen de **NASA FIRMS** (API `area`, máx. 5 días por petición, 5000 transacciones por 10 min por `MAP_KEY`; la API por país figura como no disponible).

## What Changes

- `events.json` (configuración): tipos de evento (`wildfire`, `flood`, `radar`, `vegetation`, `deformation`), palabras clave es/en, capas por tipo, cómo leer los colores, fuente de estadísticas y disponibilidad.
- `layers.json`: nuevo tipo `gibs-wmts` con dimensión de tiempo (`{Time}`), matriz de teselas y leyenda oficial.
- `SceneState`: campos `/event` (tipo, lugar, rango) y `/time/date` (día mostrado).
- Nueva vista **`events`** (ruta `eventos`, motor 2.5D con proyección globo): capas GIBS por fecha, selector de día, leyendas, cómo leer la imagen, fuentes y estadísticas.
- **Backend `compute-py`, módulo `events`:** `GET /api/events/fires/stats` (conteo mensual, total y día pico) y `GET /api/events/fires` (puntos GeoJSON de un día) desde FIRMS, filtrados por el **límite real de Bolivia** (Natural Earth, dominio público) o el bbox del lugar, con caché en disco.
- **Agente:** herramientas `show_event`, `set_event_date` y `get_fire_stats`; recibe la fecha de hoy para interpretar "últimos 2 años".

## Capabilities

### New Capabilities
- `event-catalog`: tipos de evento y presets de imágenes por tipo.
- `event-explorer`: vista de eventos con capas temporales GIBS.
- `fire-stats`: estadísticas y focos FIRMS filtrados por lugar.

### Modified Capabilities
- `scene-shadow` (07): `/event` y `/time/date`.
- `ui-agent` (08): herramientas de eventos.

## Impact

- **Frontend:** `assets/config/events.json`, `layers.json`, `routes.json`, `scene.model.ts`, motor 2.5D (capas temporales y puntos), `features/event-explorer`.
- **Backend:** `modules/events` (FIRMS + límites), `ui_agent` (herramientas), contrato `fire-stats.schema.json`.
- **Secretos:** `FIRMS_MAP_KEY` en `.env` (gratis, se pide con un email en firms.modaps.eosdis.nasa.gov/api/map_key). Sin key, las estadísticas responden `firms_not_configured` y el agente lo dice; las imágenes GIBS funcionan igual.
- **Cero mocks:** todas las imágenes y cifras son de NASA (GIBS, FIRMS). Si una fecha no tiene cobertura, la UI y el agente lo dicen.
