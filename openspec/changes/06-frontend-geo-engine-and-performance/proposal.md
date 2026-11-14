## Why

La arquitectura del frontend ([`docs/03-frontend-architecture.md`](../../../docs/03-frontend-architecture.md)) define bien la estructura Angular 22 (core/layout/shared/features, Signals, Smart/Dumb, 3 archivos por componente), pero no define **cómo** se renderizan y procesan los datos geoespaciales pesados en el navegador, ni el diseño visual. Sin esa definición, cada feature resolvería por su cuenta el mapa, la lectura de datos y el cálculo por píxel, con riesgo de:

- Re-renderizar Angular en cada frame del mapa (cámara, animación temporal) y degradar la fluidez.
- Bloquear el hilo principal con cálculos raster (umbrales de agua, diferencias entre fechas, ratios HH/HV).
- Cargar librerías WebGL pesadas (deck.gl, MapLibre, Cesium) en el bundle inicial.
- Fijar en código ventanas temporales que cambian cada 12 días con nuevas adquisiciones `VALIDATED`.
- Tener estilos inconsistentes entre features.

Además, el equipo quiere una **vista de planeta** con el satélite NISAR en órbita (posición calculada en tiempo real), una **vista 3D de deformación** y la interfaz en **español e inglés con cambio en vivo**.

Este cambio agrega **dos motores en TypeScript puro** dentro de `core/` (2.5D y 3D), desacoplados de Angular, fija los requisitos de rendimiento del SPA y adopta un sistema de diseño común. No introduce un segundo framework de UI.

## What Changes

- **`core/map-engine/`:** MapLibre GL JS (proyección globo + terreno DEM) con deck.gl como overlay, para el análisis de la cuenca.
- **`core/globe-engine/`:** CesiumJS (sin Cesium ion) para la vista de planeta con NISAR en órbita y la deformación InSAR en 3D.
- **`core/data-access/`:** `geotiff.js` para COG, protocolo `pmtiles` y clientes de catálogo, series (ya cortadas por el backend) y órbita; **solo** apuntan a `gateway-ts` (excepción: mapas base públicos sin clave de NASA GIBS declarados en configuración).
- **`core/workers/`:** Web Workers (Comlink) para cálculo raster y predicciones orbitales (SGP4 con `satellite.js`); WebGPU con respaldo WebGL2.
- Las escalas de color, rangos y umbrales por defecto de cada capa los define el backend en el catálogo; el frontend solo los aplica.
- **Nueva feature `features/orbit-view/`:** satélite en tiempo real, órbita, traza, franja aproximada, próximo paso sobre Cochabamba y enlace a la última adquisición real.
- **Componentes dumb nuevos** (3 archivos cada uno): `map-canvas`, `globe-canvas`, `time-series-chart` (uPlot), `pass-countdown`.
- **Configuración del SPA:** zoneless, presupuestos de bundle, carga diferida de motores, Service Worker, estado compartible en URL, i18n en vivo con Transloco (es/en).
- **Sistema de diseño "Control de Misión"** ([`docs/06-design-system.md`](../../../docs/06-design-system.md)): oscuro, monocromático, tipografía Barlow, botones de contorno; el color solo aparece en los datos.
- `temporal-lab` obtiene las fechas disponibles desde el catálogo en lugar de constantes.
- Recomendaciones al backend (sin modificar sus módulos): contratos en `backend/shared/contracts/`, endpoint de órbita con caché, terreno quantized-mesh de la cuenca, textos didácticos por idioma.

## Capabilities

### New Capabilities
- `frontend-geo-engine`: motor 2.5D (MapLibre + deck.gl), lectura de COG/PMTiles, cálculo raster en workers, escalas definidas por el backend.
- `frontend-orbit-view`: motor 3D (Cesium) con NISAR en órbita en tiempo real, próximo paso sobre Cochabamba y deformación 3D.
- `frontend-performance`: zoneless, presupuestos de bundle, carga diferida de motores, caché, estado en URL, responsive, i18n en vivo.
- `frontend-design-system`: tokens, tipografía, componentes base y reglas visuales.

### Modified Capabilities
- Ninguna (no existen specs vivas en `openspec/specs/` todavía).

## Impact

**Áreas del frontend afectadas**
- `core/`: nuevos `map-engine/`, `globe-engine/`, `data-access/`, `workers/`; servicios adaptadores en `core/services/`; estado en `core/state/`.
- `shared/components/`: `map-canvas`, `globe-canvas`, `time-series-chart`, `pass-countdown` y componentes base del sistema de diseño (botones, paneles, badges, leyendas).
- `features/`: nueva `orbit-view`; `basin-map`, `temporal-lab` y `risk-dashboard` consumen el motor 2.5D vía servicios.
- `layout/main-shell`: barra superior transparente con `pass-countdown` y selector de idioma.
- Configuración: `angular.json` (budgets, service worker, assets de Cesium), `app.config.ts` (zoneless, Transloco, router con estado en URL), `src/styles/_tokens.scss`.

**Módulos backend afectados**
- Ninguno se modifica. Se **depende** de `gateway-ts` (`catalog-tiles`, `gamc-proxy`, `orchestrator`) y se proponen: `GET /api/orbit/nisar` (TLE de CelesTrak cacheado ≥ 2 h) y el tileset quantized-mesh de la cuenca generado por `geoprocessing`.

**Fuentes reales de `data-map.json` consumidas (vía gateway)**
- `nisar_gcov` (COG por fecha/polarización; series ya cortadas desde los cubos Zarr por el backend), `nisar_gunw` (COG desplazamiento/coherencia), `dem` (terrain-RGB y quantized-mesh), `gpm_imerg` (tablas), `gamc_wms` (7 servicios proxied).

**Fuentes reales adicionales**
- Elementos orbitales públicos de NISAR (CelesTrak), vía `gateway-ts`.
- Imagen base NASA GIBS (WMTS público, sin credenciales).
- Pendiente de agregar a `data-map.json` por el equipo dueño del archivo.

**Cumplimiento cero mocks**
- Los motores no incluyen datos embebidos ni generadores sintéticos. La posición del satélite se calcula a partir de elementos orbitales reales y se rotula como calculada. Mientras el pipeline no produzca productos, el desarrollo usa un recorte **real** pequeño (una fecha GCOV sobre `area_of_interest.core_city`) servido por `catalog-tiles`.

**Dependencias nuevas (frontend `package.json`)**
- `maplibre-gl`, `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/geo-layers`, `@deck.gl/mapbox`, `cesium`, `satellite.js`, `geotiff`, `pmtiles`, `uplot`, `comlink`, `@jsverse/transloco`, `@fontsource/barlow`. Todas framework-agnósticas o de Angular, con licencias abiertas (MIT, BSD, Apache-2.0, OFL).
