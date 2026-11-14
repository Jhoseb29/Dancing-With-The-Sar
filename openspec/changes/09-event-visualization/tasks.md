## 1. Contratos y configuración

- [x] 1.1 `scene-state`/`scene-patch` schema: `/event`, `/time/date`
- [x] 1.2 `ui-config.schema.json`: capas `gibs-wmts` y archivo `events.json`
- [x] 1.3 `layers.json` (capas GIBS verificadas), `events.json`, `routes.json` (`events`)
- [x] 1.4 `fire-stats.schema.json`

## 2. Frontend

- [x] 2.1 Modelo y validación del shadow con evento y fecha
- [x] 2.2 Motor 2.5D: capas `gibs-wmts` por fecha y puntos GeoJSON de focos
- [x] 2.3 `features/event-explorer`: panel, selector de día, leyendas, lectura, estadísticas
- [x] 2.4 i18n es/en

## 3. Backend

- [x] 3.1 `modules/events`: límite de Bolivia (Natural Earth), adaptador FIRMS con caché, endpoints stats y puntos
- [x] 3.2 `ui_agent`: `show_event`, `set_event_date`, `get_fire_stats`, fecha de hoy en contexto, prompt

## 4. Verificación

- [x] 4.1 Radar NISAR en Cochabamba (2026-10-25) visto en el navegador; 18 fechas con cobertura verificadas
- [ ] 4.1b Ver en el navegador flood y vegetation (teselas GIBS verificadas con 200 y contenido, vista no revisada)
- [x] 4.2 Agente: "imagen de radar NISAR" e "incendios en Bolivia últimos 2 años" (sin FIRMS: lo dice y muestra MODIS)
- [ ] 4.2b Agente: "inundaciones en Cochabamba"
- [x] 4.3 FIRMS con key: 259.768 focos en Bolivia (2024-11-14 → 2026-11-14), día pico 2025-10-11 (6.175), filtrado por frontera real; caché alineada y corte SP/NRT verificados
- [x] 4.4 Build sin warnings, sin keys en `dist/`
