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
- [x] 4.1b Ver en el navegador flood y vegetation (2026-11-14): vegetación OK (solo NDVI); en flood se quitó OPERA DSWx-S1 (ver 6.2)
- [x] 4.2 Agente: "imagen de radar NISAR" e "incendios en Bolivia últimos 2 años" (sin FIRMS: lo dice y muestra MODIS)
- [x] 4.2b Agente: "Muéstrame las inundaciones en Cochabamba" → `show_event(flood, cochabamba-basin)`, explica los colores oficiales de la leyenda; las capas GAMC de la cuenca quedan intactas
- [x] 4.3 FIRMS con key: 259.768 focos en Bolivia (2024-11-14 → 2026-11-14), día pico 2025-10-11 (6.175), filtrado por frontera real; caché alineada y corte SP/NRT verificados
- [x] 4.4 Build sin warnings, sin keys en `dist/`

## 6. Ajustes tras revisión en el navegador (2026-11-14)

- [x] 6.1 Capas por vista: los eventos ya no escriben `/layers` (era compartido con la cuenca y borraba las capas GAMC). El mapa dibuja en `events` las capas de `events.json` del evento activo y en el resto solo las capas `gamc-wms` del shadow. Mismo cambio en `show_event` del backend.
- [x] 6.2 Inundaciones sin OPERA DSWx-S1: su colormap oficial pinta "no agua" en blanco opaco y "enmascarado por terreno" en gris; sobre el Tunari tapaba el mapa con rectángulos de escenas. Quedan MODIS 7-2-1 + MODIS Flood 2-Day. La guía usa los colores oficiales: celeste agua, rojo inundación, amarillo recurrente, gris sin datos.
- [x] 6.3 El estado reportado quita las capas que ya no se dibujan (el agente las leía con `get_view`).
- [x] 6.4 Barra superior con velo negro plano (`--color-overlay`, sin degradado): legible sobre imágenes claras (nubes). Actualizado `docs/06-design-system.md`.
- [x] 6.5 Fondo de incendios e inundaciones: VIIRS NOAA-20 falso color en vez de MODIS Terra 7-2-1 (sin franjas negras entre órbitas). Verificado a escala de globo y con fecha histórica (2025-10-11).
- [x] 6.6 Panel lateral ocultable (`shared/components/side-panel`, dumb): botón "Ocultar ✕" o Esc lo esconde y deja el mapa libre; queda un botón "☰ <nombre>" para reabrirlo. Usa el flag existente `/panels/layerPanel` (órbita, cuenca y eventos; el agente lo cambia con `set_side_panel`). Foco accesible al abrir/cerrar; en móvil el botón va encima del de agente. Verificado en escritorio y 375 px.
- [x] 6.7 Herramienta del agente `set_side_panel(visible)` → `/panels/layerPanel`. Probado: "Quiero ver el globo completo, quita ese panel" lo oculta y "Vuelve a mostrar la información" lo muestra. El mapa 2.5D recalcula su margen al ocultar/mostrar el panel (el lugar queda centrado en el área libre).
