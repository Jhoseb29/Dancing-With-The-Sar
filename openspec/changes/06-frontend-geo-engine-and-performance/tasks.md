## 1. Base del proyecto Angular

- [ ] 1.1 Crear el workspace Angular 22 en `frontend/` respetando la estructura existente (`core/`, `layout/`, `shared/`, `features/`) y sin borrar los `.gitkeep` hasta tener archivos reales
- [ ] 1.2 Configurar detección de cambios zoneless en `app.config.ts` y quitar `zone.js` de `polyfills`
- [ ] 1.3 Definir presupuestos en `angular.json` (inicial 350 kB advertencia / 500 kB error, sin comprimir; estilos por componente 8 kB error) y verificar que `ng build` los aplica
- [ ] 1.4 Agregar regla ESLint `no-restricted-imports`: `core/map-engine`, `core/globe-engine`, `core/data-access` y `core/workers` no pueden importar `@angular/*`; `features/` no puede importar `maplibre-gl`, `@deck.gl/*` ni `cesium`
- [ ] 1.5 Leer la URL base del gateway y la URL de NASA GIBS desde `assets/runtime-config.json` (12-Factor III)

## 2. Sistema de diseño

- [ ] 2.1 Crear `src/styles/_tokens.scss` con los tokens de `docs/06-design-system.md` y aplicar fondo `#000000` global
- [ ] 2.2 Autohospedar Barlow 400/700 con `@fontsource/barlow` y activar `tnum` en valores numéricos
- [ ] 2.3 Componentes base en `shared/components/` (3 archivos cada uno): botón fantasma, botón secundario, toggle píldora, panel flotante, badge de madurez (trazo sólido/discontinuo/punteado), leyenda de capa
- [ ] 2.4 `layout/main-shell`: barra superior transparente con navegación, selector de idioma y espacio para `pass-countdown`
- [ ] 2.5 Verificar que no hay colores hexadecimales fuera de `_tokens.scss` ni sombras/degradados en `.scss`

## 3. i18n en vivo

- [ ] 3.1 Configurar `@jsverse/transloco` con `es` (por defecto) y `en`, archivos en `assets/i18n/` cargados bajo demanda
- [ ] 3.2 Guardar el idioma en el SignalStore y en `?lang=`; cambiar idioma sin recargar ni perder el estado de la vista

## 4. Acceso a datos (`core/data-access/`)

- [ ] 4.1 `catalog.client.ts`: cliente de `GET /api/catalog/layers` y `GET /api/catalog/timeline` tipado con los contratos de `backend/shared/contracts/`
- [ ] 4.2 `pmtiles-protocol.ts`: registrar `pmtiles://` en MapLibre apuntando a `/api/catalog/files/...`
- [ ] 4.3 `cog-reader.ts`: lectura de COG con `geotiff.js` por HTTP Range; verificar respuestas 206 contra un COG real del catálogo
- [ ] 4.4 `series.client.ts`: cliente de `GET /api/series` (series ya cortadas por el backend); verificar contra una serie GCOV real
- [ ] 4.5 Precarga del COG de la fecha siguiente para la animación temporal
- [ ] 4.6 `orbit.client.ts`: cliente de `GET /api/orbit/nisar` con el `epoch` del TLE

## 5. Motor 2.5D (`core/map-engine/`)

- [ ] 5.1 `geo-engine.ts`: crear MapLibre con proyección `globe`, encuadre inicial `area_of_interest.core_city` y terreno desde terrain-RGB del DEM
- [ ] 5.2 Integrar deck.gl con `MapboxOverlay({ interleaved: true })`
- [ ] 5.3 `layer-registry.ts` y capas coloreadas en GPU con `display` del catálogo (sin rangos ni paletas definidos en el frontend): GCOV (dB), GUNW (desplazamiento mm + coherencia), WMS GAMC vía `/api/gamc/wms`, PMTiles de riesgo
- [ ] 5.4 Exigir `maturity`, `track`, `frame`, `direction` en cada descriptor NISAR (error si faltan)
- [ ] 5.5 Liberar contexto WebGL, workers y listeners en `destroy()`

## 6. Motor 3D y vista de planeta (`core/globe-engine/`, `features/orbit-view/`)

- [ ] 6.1 Instalar `cesium`, copiar `Workers/`, `Assets/`, `Widgets/`, `ThirdParty/` como assets en `angular.json` y configurar `CESIUM_BASE_URL`
- [ ] 6.2 `globe-engine.ts`: Viewer sin Cesium ion, sin widgets por defecto, imagen base NASA GIBS (WMTS) desde `runtime-config.json`, reloj sincronizado con la hora actual
- [ ] 6.3 `satellite-entity.ts`: posición de NISAR con `satellite.js` (SGP4) en cada frame a partir del TLE de `/api/orbit/nisar`
- [ ] 6.4 `orbit.worker.ts`: órbita (±1 vuelta), traza sobre el suelo y próximos pasos sobre `core_city` en 48 h
- [ ] 6.5 `swath.ts`: franja aproximada (~240 km) rotulada como aproximada
- [ ] 6.6 `shared/components/globe-canvas/` y `shared/components/pass-countdown/` (3 archivos, dumb)
- [ ] 6.7 `features/orbit-view/` (ruta lazy): satélite, trayectoria, cuenta regresiva, aviso "posición calculada / paso ≠ adquisición", antigüedad del TLE con advertencia > 3 días, última adquisición real desde `CatalogTimeline`
- [ ] 6.8 Transición "ver Cochabamba": vuelo de cámara y navegación a `basin-map` conservando idioma y estado en la URL
- [ ] 6.9 `deformation-layer.ts`: GUNW coloreado con `display` en un worker y drapeado sobre el terreno quantized-mesh; mostrar madurez y par de fechas; mensaje claro si el terreno aún no existe
- [ ] 6.10 Verificar que Cesium y MapLibre nunca están activos a la vez y que el motor se destruye al salir de la ruta

## 7. Cálculo raster (`core/workers/`)

- [ ] 7.1 `raster.worker.ts` + API Comlink: aplicar escala, umbral de agua, diferencia entre fechas, ratio HH/HV con buffers transferibles
- [ ] 7.2 Ruta WebGPU (`compute.wgsl`) con detección de `navigator.gpu` y fallback WebGL2/worker
- [ ] 7.3 Verificar en el perfilador que mover el umbral no genera tareas > 50 ms en el hilo principal

## 8. Puente Angular

- [ ] 8.1 `core/services/geo-engine.service.ts` y `globe-engine.service.ts`: adaptadores que exponen Signals con throttle (`requestAnimationFrame`/`moveend`; datos del satélite como máximo 1 vez por segundo)
- [ ] 8.2 `core/state/view.store.ts` (NgRx SignalStore): ruta, cuenca, fechas, capas, polarización, madurez, idioma; sincronizado con query params (debounce 300 ms)
- [ ] 8.3 `shared/components/map-canvas/` (3 archivos, dumb): hospeda el canvas y emite eventos de clic/selección
- [ ] 8.4 `shared/components/time-series-chart/` (3 archivos, dumb, uPlot): serie GCOV + lluvia GPM en el mismo eje; cargado con `@defer`

## 9. Integración en features

- [ ] 9.1 `basin-map`: usar `map-canvas` + servicio adaptador; `GetFeatureInfo` del GAMC al hacer clic vía `/api/gamc/wms`
- [ ] 9.2 `temporal-lab`: fechas y ventanas desde `CatalogTimeline` (sin fechas fijas en código), animación con COG por fecha, series desde `/api/series`, gráfica sincronizada
- [ ] 9.3 `risk-dashboard`: reutilizar el motor 2.5D con capas PMTiles de riesgo y `Emergencias`

## 10. Rendimiento, caché y alcance

- [ ] 10.1 Configurar `@angular/service-worker` (`performance` para teselas, terreno, GIBS y leyendas; `freshness` para catálogo, series y órbita)
- [ ] 10.2 Verificar que el bundle inicial no contiene MapLibre, deck.gl ni Cesium (`source-map-explorer` o estadísticas del build)
- [ ] 10.3 Revisar vistas a 360 px de ancho (hoja inferior), navegación por teclado y contraste AA

## 11. Coordinación con backend (sin modificar módulos backend)

- [ ] 11.1 Acordar los contratos `CatalogLayer`, `LayerDisplay`, `CatalogTimeline`, `TimeSeries` y `OrbitElements` (design D9) en `backend/shared/contracts/`
- [ ] 11.2 Pedir un primer recorte real (1 fecha GCOV sobre `core_city` + terrain-RGB) servido por `catalog-tiles` para desarrollar sin mocks
- [ ] 11.3 Pedir el endpoint `GET /api/orbit/nisar` en `gateway-ts` (TLE de CelesTrak cacheado ≥ 2 h, con `epoch`)
- [ ] 11.4 Pedir a `geoprocessing` el tileset quantized-mesh del Copernicus DEM de la cuenca, servido por `catalog-tiles`
- [ ] 11.5 Pedir que el Harness 2 entregue textos en `es` y `en`
- [ ] 11.6 Pedir al dueño de `data-map.json` agregar las fuentes de órbita (CelesTrak) y NASA GIBS
