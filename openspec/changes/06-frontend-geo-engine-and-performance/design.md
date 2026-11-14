## Context

El SPA Angular 22 (`./frontend`) solo tiene la estructura de carpetas. `docs/03-frontend-architecture.md` define convenciones de UI (Signals, Smart/Dumb, 3 archivos, lazy loading) pero no el renderizado geoespacial ni el rendimiento. Los productos que el frontend consumirá ya están decididos en `docs/04`: COG (HTTP Range), Zarr `(time, y, x)`, PMTiles y tablas Parquet/CSV, todos expuestos por `gateway-ts` (`catalog-tiles`, `gamc-proxy`, `orchestrator`).

Además de la vista de cuenca, el equipo quiere una **vista de planeta** con el satélite NISAR en órbita y su posición calculada en tiempo real, y una **vista 3D de deformación** InSAR sobre el terreno del Tunari.

Restricciones aplicables: cero mocks, cero credenciales en el cliente, 12-Factor, estructura `core/layout/shared/features`, 3 archivos por componente, agentes sin `git commit`/`git push`.

## Goals / Non-Goals

**Goals:**
- Un motor 2.5D reutilizable por `basin-map`, `temporal-lab` y `risk-dashboard`.
- Un motor 3D de globo para `orbit-view` (satélite en órbita) y la vista de deformación.
- Interacción fluida (60 fps objetivo al navegar; sin tareas largas > 50 ms en el hilo principal durante cálculos raster u orbitales).
- Bundle inicial pequeño; librerías WebGL solo en rutas que las usan.
- Interfaz en español e inglés con cambio de idioma en vivo.
- Compatibilidad total con las reglas Angular del equipo.

**Non-Goals:**
- No se introduce un segundo framework de UI (React, Vue, etc.).
- No se modifica ningún módulo de `backend/`; solo se documentan los contratos y endpoints que el frontend necesita.
- No se muestra telemetría real del satélite: la posición es **calculada** a partir de elementos orbitales públicos.
- No se define el contenido de `didactic-insights` ni `data-provenance` más allá de su consumo de datos.

## Decisions

### D1. Angular para UI + motores en TypeScript puro (sin segundo framework)
Todas las librerías necesarias (MapLibre GL JS, deck.gl, CesiumJS, satellite.js, geotiff.js, pmtiles, uPlot, Comlink) son framework-agnósticas. Encapsularlas en `core/map-engine/`, `core/globe-engine/`, `core/data-access/` y `core/workers/` sin importar `@angular/*` mantiene el rendimiento (los motores no pasan por la detección de cambios) y permite probarlos de forma aislada.
- *Alternativa descartada:* React/deck.gl dentro de Angular como Web Component. Duplica runtimes (~45 kB+ gzip extra), complica el estado y rompe la regla de Angular 22 del equipo.
- *Alternativa descartada:* wrappers Angular de terceros para MapLibre o Cesium. Agregan una capa de detección de cambios por evento y dependen de mantenedores externos.

### D2. Dos motores con responsabilidades separadas (DECIDIDO)
| Motor | Tecnología | Vistas | Por qué |
| :--- | :--- | :--- | :--- |
| `map-engine` (2.5D) | MapLibre GL JS (proyección `globe`, terreno) + deck.gl (`MapboxOverlay`, `interleaved: true`) | `basin-map`, `temporal-lab`, `risk-dashboard` | Ligero, capas GPU para rasters con escala dinámica, PMTiles y WMS nativos. |
| `globe-engine` (3D) | CesiumJS | `orbit-view` (planeta + satélite) y vista de deformación 3D | Único que dibuja objetos a ~747 km de altura con órbitas, trayectorias y terreno geodésico; reloj y tiempo integrados. |

- Los dos motores **nunca** están activos a la vez: cada uno vive en rutas lazy distintas y se destruye al salir.
- *Alternativa descartada:* solo MapLibre. No permite dibujar el satélite en órbita alrededor del globo.
- *Alternativa descartada:* solo Cesium. Más pesado para el análisis diario de la cuenca y sin el ecosistema de capas GPU de deck.gl.
- *Alternativa descartada:* three.js con un globo propio. Habría que reimplementar proyección, terreno e imágenes que Cesium ya resuelve.

### D3. Capas de código y dependencias permitidas
```
features/*  ──>  core/services/geo-engine.service.ts    ──>  core/map-engine/*   (MapLibre + deck.gl)
            ──>  core/services/globe-engine.service.ts  ──>  core/globe-engine/* (Cesium + satellite.js)
                       (Signals)                               │
                                                               ├──> core/data-access/* (geotiff, pmtiles, catálogo, series, órbita)
shared/components/{map-canvas, globe-canvas} (dumb, host)      └──> core/workers/* (Comlink + WebGPU/WebGL2, SGP4)
```
- `features/` y `shared/` nunca importan `core/map-engine/` ni `core/globe-engine/` directamente; solo los servicios adaptadores.
- `core/map-engine/`, `core/globe-engine/`, `core/data-access/` y `core/workers/` no importan `@angular/*`. Se verifica con una regla `no-restricted-imports` de ESLint.
- La regla de 3 archivos aplica a componentes; los archivos de los motores son módulos `.ts` igual que cualquier servicio.

Estructura propuesta:
```
core/
  map-engine/      geo-engine.ts, layer-registry.ts, layers/{gcov,gunw,dem,wms,pmtiles}.layer.ts, colormaps.ts
  globe-engine/    globe-engine.ts, satellite-entity.ts, ground-track.ts, swath.ts, deformation-layer.ts
  data-access/     cog-reader.ts, pmtiles-protocol.ts, catalog.client.ts, series.client.ts, orbit.client.ts
  workers/         raster.worker.ts, raster.api.ts, orbit.worker.ts (SGP4), gpu/{compute.wgsl, fallback.glsl}
  services/        geo-engine.service.ts, globe-engine.service.ts, i18n.service.ts (adaptadores → Signals)
  state/           view.store.ts (NgRx SignalStore: cuenca, fechas, capas, madurez, idioma; sincronizado con URL)
shared/components/
  map-canvas/            .ts .html .scss
  globe-canvas/          .ts .html .scss
  time-series-chart/     .ts .html .scss
  pass-countdown/        .ts .html .scss
features/
  orbit-view/            (nueva feature lazy)
assets/i18n/             es.json, en.json
```

### D4. Puente motor → Signals con throttle
Los adaptadores crean los motores fuera del ciclo de Angular (zoneless lo hace natural), escuchan eventos y actualizan Signals solo en `moveend`/`idle` o como máximo una vez por `requestAnimationFrame`. La posición del satélite se dibuja dentro del render loop de Cesium y **no** se publica como Signal en cada frame; solo se publican datos de UI (altitud, lat/lon redondeadas, próximo paso) como máximo una vez por segundo.

### D5. Cálculo raster: worker por defecto, GPU cuando conviene
- Operaciones por píxel sobre teselas (aplicar la escala del catálogo, umbral de agua, diferencia entre fechas, ratio HH/HV): shader de deck.gl (WebGL2) para visualización inmediata.
- Estadísticas y máscaras sobre bloques grandes: Web Worker con `Float32Array` transferibles; WebGPU compute cuando `navigator.gpu` existe.
- Resultado idéntico en ambas rutas; la ruta GPU solo acelera.

### D6. Datos: el backend corta, el frontend muestra (DECIDIDO)
- **Series temporales (píxel o cuenca):** siempre ya cortadas por el backend vía `orchestrator` → `compute-py` (coincide con `docs/02` §1.3 "slicing dinámico de Zarr"). Así los Harnesses y el usuario ven exactamente los mismos números. El cliente **no lee Zarr**.
- **Mapas por fecha y animación:** COG por fecha/polarización (ya producidos por `geoprocessing`) leídos por HTTP Range a través de `catalog-tiles`, con precarga de la fecha siguiente.
- **Vectores:** PMTiles por HTTP Range.
- *Alternativa descartada:* leer chunks Zarr en el navegador con `zarrita.js`. Duplicaría en el cliente lógica que ya vive en `compute-py` y separaría lo que ve el usuario de lo que interpretan los Harnesses.

### D6b. Escalas de visualización definidas por el backend (DECIDIDO)
- El backend (`geoprocessing`, expuesto por `catalog-tiles`) define por capa: unidades, `value_range` de visualización, paleta (`colormap`), `nodata` y, cuando aplique, umbrales por defecto (p. ej. umbral de agua en dB) con su justificación.
- El frontend recibe **valores físicos** (dB, mm, coherencia 0–1), no imágenes pre-coloreadas, y aplica la escala del catálogo. En `map-engine` se aplica en GPU (shader deck.gl); en `globe-engine` el worker colorea el COG en un canvas que Cesium usa como imagen sobre el terreno.
- El frontend MUST NOT inventar escalas propias; los controles interactivos parten del valor por defecto del catálogo.

### D7. Rendimiento del SPA
- Zoneless; sin `zone.js`.
- Presupuestos en `angular.json` (inicial: advertencia 350 kB / error 500 kB, tamaño sin comprimir que es lo que mide Angular).
- Lazy loading por ruta + `@defer` para la gráfica uPlot. Cesium y satellite.js solo dentro de `orbit-view` y la vista de deformación.
- Los recursos estáticos de Cesium (`Workers/`, `Assets/`, `Widgets/`, `ThirdParty/`) se copian como assets en `angular.json` y `CESIUM_BASE_URL` apunta a ellos; no se cargan hasta entrar a la ruta.
- `@angular/service-worker`: grupos `performance` para teselas/leyendas/imágenes GIBS y terreno; `freshness` para catálogo, series y órbita.
- Estado de vista en query params (debounce 300 ms) mediante el SignalStore.

### D8. i18n en vivo con Transloco (DECIDIDO)
- `@jsverse/transloco` con idiomas `es` (por defecto) y `en`, archivos en `assets/i18n/{lang}.json` cargados bajo demanda.
- Cambio de idioma sin recargar; el idioma activo vive en el SignalStore y en la URL (`?lang=en`) para compartir vistas.
- Los textos generados por el backend (Harness 2) se piden en el idioma activo; el frontend no traduce contenido científico por su cuenta.
- *Alternativa descartada:* `@angular/localize` (un build por idioma). Obliga a recargar al cambiar de idioma.

### D9. Contratos requeridos (a definir en `backend/shared/contracts/`, no implementados aquí)
- `CatalogLayer`: `{ id, product: 'GCOV'|'GUNW'|'DEM'|'PMTILES'|'TABLE', format: 'cog'|'pmtiles'|'parquet'|'csv', url, bbox, maturity, track, frame, direction, crid, acquisition_date | pair_dates, polarization?, display: LayerDisplay }`
- `LayerDisplay` (definido por el backend, D6b): `{ units, nodata, value_range: [min, max], colormap: { name, stops: [{ value, color }] }, defaults?: { water_threshold_db?, ... }, legend_title }`
- `CatalogTimeline`: `{ dates[], windows: [{ id, start, end, maturity }], gaps: [{ start, end, reason }] }`
- `TimeSeries`: `{ layer_id, location: point|basin_id, unit, points: [{ date, value, maturity }] }`
- `OrbitElements` (D10): `{ satellite: 'NISAR', norad_id, tle_line1, tle_line2, epoch, source: 'CelesTrak', fetched_at, valid_hint_hours }`
- Terreno 3D (D11): tileset quantized-mesh de la cuenca servido como archivos estáticos (`layer.json` + teselas).
- Rutas esperadas: `GET /api/catalog/layers`, `GET /api/catalog/timeline`, `GET /api/catalog/files/{path}` (Range), `GET /api/series?...`, `GET /api/gamc/wms?service_id=...&REQUEST=...`, `GET /api/orbit/nisar`, `GET /api/terrain/{z}/{x}/{y}.terrain` + `GET /api/terrain/layer.json`.

### D10. Satélite NISAR en órbita (DECIDIDO)
- **Fuente:** elementos orbitales públicos (TLE) de CelesTrak. `gateway-ts` los descarga y cachea **al menos 2 horas** (CelesTrak pide no consultar más seguido) y los expone en `GET /api/orbit/nisar`. El frontend nunca llama a CelesTrak.
- **Cálculo:** `satellite.js` (SGP4) en el cliente. La posición del frame actual se calcula en el hilo principal dentro del render de Cesium (es una operación de microsegundos). Las predicciones pesadas (trayectoria de las próximas órbitas, próximos pasos sobre Cochabamba en 48 h) se calculan en `orbit.worker.ts`.
- **Qué se dibuja en `orbit-view`:**
  - El satélite a su altitud real, en tiempo real (reloj de Cesium sincronizado con la hora actual), con opción de acelerar el tiempo.
  - La órbita (una vuelta hacia atrás y hacia adelante) y la traza sobre el suelo.
  - La franja aproximada que observa el radar (~240 km de ancho), marcada como **aproximada**.
  - El próximo paso sobre `area_of_interest.core_city` con cuenta regresiva (`pass-countdown`).
  - La última adquisición real de Cochabamba según `CatalogTimeline`, con su madurez.
- **Honestidad del dato:** la UI MUST indicar que la posición es calculada a partir de elementos orbitales públicos y que un paso del satélite no garantiza que se haya tomado una imagen (eso depende del plan de observación de NISAR).
- **Transición:** desde `orbit-view` el usuario puede "bajar" a Cochabamba y pasar a `basin-map` conservando el estado en la URL.

### D11. Cesium sin Cesium ion (DECIDIDO)
- No se usa el token de Cesium ion (sería una credencial en el cliente y una dependencia externa de pago).
- **Imagen base:** NASA GIBS WMTS (p. ej. Blue Marble), servicio público sin clave. Su URL se lee de `runtime-config.json` (12-Factor III).
- **Terreno:** el Copernicus DEM de la cuenca procesado por `geoprocessing` a **quantized-mesh** (formato que Cesium requiere; el terrain-RGB de MapLibre no sirve) y servido por `catalog-tiles`. Fuera de la cuenca se usa el elipsoide.
- **Excepción acotada a "solo vía gateway":** se permiten mapas base públicos y sin credenciales (NASA GIBS) directamente desde el cliente, declarados en `runtime-config.json`. Los productos del proyecto (NISAR, DEM, GAMC, órbita) siguen pasando siempre por `gateway-ts`.

### D12. Sistema de diseño "Control de Misión" (DECIDIDO)
- Base: referencia de estilo aeroespacial oscura y monocromática entregada por el equipo, documentada y adaptada en [`docs/06-design-system.md`](../../../docs/06-design-system.md).
- Tokens en `frontend/src/styles/_tokens.scss`; los componentes solo usan tokens.
- Adaptaciones: el color existe solo en los datos (paletas del backend); paneles con fondo negro al 72 % sobre el mapa por legibilidad; texto secundario `#9a9aa3` por contraste WCAG; datos con texto ≥ 12 px; Barlow autohospedada en lugar de la tipografía propietaria de la referencia; sin nombres ni logos de terceros.
- Encaja con la arquitectura: el globo (Cesium) y el mapa (MapLibre) son la "imagen a pantalla completa" del estilo; los controles flotan en el tercio izquierdo; la cuenta regresiva del próximo paso de NISAR ocupa el lugar del widget superior derecho.

### Cumplimiento 12-Factor (frontend)
- **III Config:** URL base del gateway y de mapas base públicos por configuración de runtime (`assets/runtime-config.json` generado en despliegue), no en código.
- **IV Backing services:** el frontend solo conoce `gateway-ts` y los mapas base públicos declarados.
- **IX Disposability:** los motores liberan WebGL, workers, entidades Cesium y listeners en `DestroyRef` al salir de la ruta.
- **XI Logs:** sin datos sensibles en consola; errores de los motores a un logger central en `core/services/`.

## Risks / Trade-offs

- **[Riesgo] WebGPU desigual entre navegadores** → Mitigación: WebGL2/worker como ruta por defecto; WebGPU solo como acelerador.
- **[Riesgo] Tamaño de deck.gl y Cesium** → Mitigación: imports selectivos, carga lazy por ruta, assets de Cesium fuera del bundle; presupuestos que fallan el build si algo pesado entra al bundle inicial.
- **[Riesgo] TLE desactualizado o CelesTrak caído** → Mitigación: el gateway sirve el último TLE cacheado con su `epoch`; la UI muestra la antigüedad del dato y advierte si supera unos días.
- **[Riesgo] Terreno quantized-mesh depende del backend** → Mitigación: la vista de órbita funciona con el elipsoide; el terreno solo es necesario para la deformación 3D.
- **[Riesgo] Contratos backend aún no definidos** → Mitigación: D9 propone los contratos; el frontend avanza con un recorte real y pequeño servido por `catalog-tiles` en cuanto exista.
- **[Trade-off] Dos motores 3D/2.5D** → Más código que mantener, a cambio de usar la herramienta correcta en cada vista y no cargar Cesium en el análisis diario.
- **[Trade-off] Series solo vía API** → Cada consulta de serie es una petición al backend; se mitiga con caché `freshness` del Service Worker y caché en `orchestrator`.
- **[Trade-off] Transloco en runtime** → Una dependencia y unos kB extra a cambio de cambiar de idioma sin recargar.

## Open Questions

Ninguna pendiente en el frontend. Resueltas: series ya cortadas por el backend (D6), escalas definidas por el backend (D6b), idioma en vivo con Transloco (D8), Cesium para planeta + deformación (D2, D10, D11), sistema de diseño (D12).

Pendiente de coordinar con backend: quién genera el quantized-mesh de la cuenca y cuándo (tarea 8.4).
