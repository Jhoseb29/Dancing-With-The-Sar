# 03 · Arquitectura del Frontend (`./frontend` · Angular 22)

El frontend es una aplicación web interactiva construida con **Angular 22** y **TypeScript estricto**, enfocada en comunicar de manera visual e intuitiva cambios en la superficie terrestre (SAR/InSAR), hidrometeorología (GPM IMERG), riesgo por cuenca en Cochabamba y explicaciones didácticas generadas desde datos reales.

---

## 1. Estructura de Carpetas Obligatoria

```text
frontend/
└── src/
    ├── app/
    │   ├── core/          # Singleton services, interceptores, runtime config, estado global con Signals
    │   │   ├── config/
    │   │   ├── interceptors/
    │   │   ├── services/
    │   │   ├── state/
    │   │   ├── map-engine/    # Motor 2.5D MapLibre + deck.gl en TS puro (sin @angular/*) — ver §4
    │   │   ├── globe-engine/  # Motor 3D Cesium: planeta, NISAR en órbita, deformación — ver §4
    │   │   ├── data-access/   # Lectores COG / PMTiles y clientes de catálogo, series y órbita — ver §4
    │   │   └── workers/       # Web Workers: cálculo raster (WebGPU/WebGL2) y órbitas (SGP4) — ver §4
    │   ├── layout/        # Shell principal, header, barra lateral de capas, selector temporal
    │   │   └── main-shell/
    │   ├── shared/        # Dumb components reutilizables, pipes, directivas y modelos UI
    │   │   ├── components/
    │   │   ├── directives/
    │   │   ├── models/
    │   │   └── pipes/
    │   └── features/      # Rutas funcionales lazy-loaded (Smart + Dumb components)
    │       ├── basin-map/
    │       ├── temporal-lab/
    │       ├── risk-dashboard/
    │       ├── didactic-insights/
    │       ├── data-provenance/
    │       └── orbit-view/    # Vista de planeta con NISAR en tiempo real — ver §4
    ├── assets/
    │   └── i18n/          # es.json, en.json (Transloco, cambio de idioma en vivo)
    └── styles/
        └── _tokens.scss   # Tokens del sistema de diseño — ver docs/06-design-system.md
```

---

## 2. Reglas de Diseño Angular 22 (Constraints)

1. **Regla estricta de 3 archivos por componente:** Cada componente (tanto en `layout/`, `shared/components/` como dentro de `features/`) debe tener exactamente **3 archivos** hermanos:
   * `<nombre>.component.ts`
   * `<nombre>.component.html`
   * `<nombre>.component.scss`
   *(No usar templates inline ni estilos inline; mantener separación clara entre lógica, estructura y estilos).*
2. **Standalone Components por defecto:** Sin `NgModule` innecesarios. Cada feature expone su archivo de rutas (`<feature>.routes.ts`) cargado mediante **Lazy Loading** (`loadChildren` / `loadComponent`) en el router raíz.
3. **Signals nativos como estado reactivo principal:**
   * Usar `signal()`, `computed()`, `effect()`, `input()`, `output()` y `toSignal()` de forma nativa.
   * Integrar **NgRx SignalStore** únicamente cuando exista estado complejo compartido entre múltiples features (por ejemplo: selección activa de cuenca, ventana temporal seca vs lluvias, filtro de madurez `BETA`/`PROVISIONAL`/`VALIDATED` y capas visibles en el mapa).
4. **Patrón Smart / Dumb Components:**
   * **Smart (Container) Components:** Viven en la raíz de cada feature (`features/<feature>/pages/` o `containers/`). Se conectan a servicios de `core/` o stores, manejan señales de carga/error y pasan datos hacia abajo.
   * **Dumb (Presentational) Components:** Viven en `shared/components/` o `features/<feature>/components/`. Solo reciben datos vía `input()` y emiten eventos vía `output()`; **no** inyectan servicios HTTP ni conocen el backend.
5. **Pipes puros para transformación visual:** Crear pipes dedicados en `shared/pipes/` para:
   * Conversión/formateo de backscatter en dB (`gamma0`)
   * Desplazamiento InSAR en milímetros (`mm`)
   * Badges de madurez científica (`BETA` / `PROVISIONAL` / `VALIDATED`)
   * Formateo de coordenadas y fechas de adquisición SAR.
6. **Seguridad y cero llaves en cliente:** Todas las llamadas a capas WMS del GAMC pasan por `gateway-ts` (`/api/gamc/...`). Ninguna credencial (`GAMC_WMS_KEY`, Earthdata, LLM) existe en el frontend.

---

## 3. Features Planificadas (MVP)

| Feature | Rol en la aplicación | Fuentes reales consumidas |
| :--- | :--- | :--- |
| **`basin-map`** | Visor geoespacial principal (MapLibre GL / deck.gl): terreno 3D DEM, capas PMTiles, overlays COG (GCOV/GUNW) y capas WMS proxied del GAMC (cuencas, drenaje, Cota 2750, emergencias) con *click-to-inspect*. | PMTiles, COG, Copernicus DEM terrain-RGB, GAMC WMS `GetMap` + `GetFeatureInfo`. |
| **`temporal-lab`** | Laboratorio multitemporal: comparación época seca (`2026-06-17`–`2026-10-20`, `PROVISIONAL`) vs inicio de lluvias (`2026-10-21+`, `VALIDATED`), animación con un **COG por fecha** y gráfica sincronizada con lluvia **GPM IMERG**. Las series por píxel o cuenca llegan **ya cortadas** por el backend desde los cubos Zarr. | COG GCOV por fecha, series GCOV cortadas por `orchestrator`, series CSV/Parquet GPM IMERG. |
| **`risk-dashboard`** | Panel de alerta temprana por cuenca/distrito: diferencia riesgo en **laderas del norte (Tunari: deslizamientos/torrenteras)** vs **valle sur (Albarrancho/Rocha: inundación/saturación)**. | `risk-assessment` + `Emergencias` GAMC + métricas derivadas. |
| **`didactic-insights`** | Visualización didáctica e interactiva de los resultados del **Harness 2** (lenguaje claro para ciudadanía, defensa civil y técnica) + consultas asistidas al módulo `llm-advisor`. | Dataset entrenado/interpretado de `harness-interpreter` + `llm-advisor`. |
| **`data-provenance`** | Transparencia científica: manifiestos reales, score y juicio del **Harness 1**, estado de calibración CRID, `track/frame` activo y advertencias de brechas (`2026-07-27` a `2026-08-10`). | Manifiestos CSV + artefactos de evaluación de `harness-analyst`. |
| **`orbit-view`** | Vista de planeta (Cesium): NISAR en órbita con posición **calculada** en tiempo real, órbita, traza, franja aproximada, cuenta regresiva al próximo paso sobre Cochabamba, última adquisición real y descenso hacia `basin-map`. Incluye la vista 3D de deformación InSAR sobre el Tunari. | TLE de NISAR vía `/api/orbit/nisar`, NASA GIBS, `CatalogTimeline`, GUNW + quantized-mesh del DEM. |

---

## 4. Motores Geoespaciales, Rendimiento e Idioma

> Especificación completa en [`openspec/changes/06-frontend-geo-engine-and-performance/`](../openspec/changes/06-frontend-geo-engine-and-performance/proposal.md). Diseño visual en [`06-design-system.md`](./06-design-system.md).

**Principio:** Angular 22 para la interfaz + **dos motores en TypeScript puro** para lo pesado. No se usa un segundo framework de UI: todas las librerías de mapa, globo y datos son framework-agnósticas.

### 4.1 Dos motores

| Motor | Tecnología | Vistas |
| :--- | :--- | :--- |
| `core/map-engine/` (2.5D) | MapLibre GL JS + deck.gl | `basin-map`, `temporal-lab`, `risk-dashboard` |
| `core/globe-engine/` (3D) | CesiumJS (sin Cesium ion) + satellite.js | `orbit-view` (planeta + NISAR en órbita) y deformación 3D |

Nunca están activos a la vez: cada uno vive en rutas lazy distintas y se destruye al salir.

### 4.2 Capas de código

```text
features/*  ──>  core/services/geo-engine.service.ts    ──>  core/map-engine/*
            ──>  core/services/globe-engine.service.ts  ──>  core/globe-engine/*
                       (Signals)                              ├──> core/data-access/*
shared/components/{map-canvas, globe-canvas} (dumb)           └──> core/workers/*
```

* `core/map-engine/`, `core/globe-engine/`, `core/data-access/` y `core/workers/` **no importan `@angular/*`** (regla ESLint). No son componentes, por lo que la regla de 3 archivos no aplica; los componentes que los usan (`map-canvas`, `globe-canvas`, `time-series-chart`, `pass-countdown`) sí la cumplen.
* Las features **nunca** importan `maplibre-gl`, `@deck.gl/*` ni `cesium`: hablan con los motores mediante los servicios adaptadores.

### 4.3 Librerías

| Necesidad | Librería | Dónde |
| :--- | :--- | :--- |
| Mapa de la cuenca, terreno 3D | **MapLibre GL JS** (proyección `globe`, terrain-RGB del DEM) | `core/map-engine/` |
| Capas GPU (rasters con escala dinámica, vectores masivos) | **deck.gl** como `MapboxOverlay` intercalado | `core/map-engine/` |
| Planeta, satélite en órbita, deformación 3D | **CesiumJS** con imagen base **NASA GIBS** y terreno quantized-mesh propio | `core/globe-engine/` |
| Posición orbital (SGP4) | **satellite.js** | `core/globe-engine/` + `core/workers/` |
| COG por HTTP Range | **geotiff.js** | `core/data-access/` |
| Capas vectoriales | Protocolo **pmtiles** para MapLibre | `core/data-access/` |
| Cálculo por píxel fuera del hilo principal | **Web Workers + Comlink**, WebGPU con respaldo WebGL2 | `core/workers/` |
| Series temporales (GCOV vs lluvia GPM) | **uPlot** | `shared/components/time-series-chart/` |
| Idioma en vivo (es/en) | **Transloco** (`@jsverse/transloco`) | `core/` + `assets/i18n/` |
| Tipografía | **Barlow** autohospedada (`@fontsource/barlow`) | `styles/` |

### 4.4 Satélite NISAR en tiempo real

* `gateway-ts` baja los elementos orbitales (TLE) de CelesTrak y los cachea al menos 2 horas en `GET /api/orbit/nisar`. El frontend nunca llama a CelesTrak.
* El navegador calcula la posición con `satellite.js` en cada frame; la órbita, la traza y los próximos pasos sobre Cochabamba (48 h) se calculan en un worker.
* La UI aclara que la posición es **calculada** (no telemetría), muestra la antigüedad del TLE y avisa que un paso del satélite no garantiza que se haya tomado una imagen.

### 4.5 Reglas de rendimiento

1. **Zoneless:** sin `zone.js`.
2. **Signals con freno:** cámara y hover se publican solo al terminar el gesto o como máximo una vez por frame; los datos del satélite, como máximo una vez por segundo.
3. **Lazy:** MapLibre, deck.gl, Cesium, satellite.js, geotiff y uPlot fuera del bundle inicial (rutas lazy y `@defer`). Los assets de Cesium se copian como estáticos y solo se piden al entrar a una vista 3D.
4. **Presupuestos en `angular.json`:** bundle inicial con advertencia en 350 kB y error en 500 kB (tamaño sin comprimir, que es lo que mide Angular; ≈ 85 kB transferidos).
5. **Service Worker:** caché `performance` para teselas, terreno, GIBS y leyendas; `freshness` para catálogo, series y órbita.
6. **Fechas desde el catálogo:** `temporal-lab` no tiene fechas fijas en código; usa `GET /api/catalog/timeline`.
7. **Estado en la URL:** ruta, cuenca, fechas, capas, polarización, vista del mapa e idioma en query params para compartir vistas.
8. **Idioma en vivo:** Transloco cambia es/en sin recargar; los textos del Harness 2 se piden al backend en el idioma activo.
9. **Alcance:** usable desde 360 px de ancho, operable con teclado, contraste AA.

### 4.6 Qué decide el backend y qué hace el frontend

| Tema | Backend | Frontend |
| :--- | :--- | :--- |
| Series temporales (píxel o cuenca) | Las corta desde los cubos Zarr (`compute-py`) y las entrega por `orchestrator`. Son los mismos números que interpretan los Harnesses. | Las pide a `/api/series` y las grafica. **No lee Zarr.** |
| Escalas de color | Define por capa unidades, rango, paleta, `nodata` y umbrales por defecto (`display` en el catálogo). | Recibe valores físicos (dB, mm) y aplica esa escala. No inventa rangos ni paletas. |
| Órbita de NISAR | Descarga y cachea el TLE (`/api/orbit/nisar`). | Calcula la posición y dibuja la órbita. |
| Terreno 3D | Genera el quantized-mesh del DEM de la cuenca. | Lo usa en Cesium para la deformación 3D. |
| Textos didácticos | El Harness 2 los genera en `es` y `en`. | Los muestra en el idioma activo. |

### 4.7 Contratos que el frontend necesita del backend

Propuestos para `backend/shared/contracts/` (detalle en `design.md`, D9): `CatalogLayer` (con `LayerDisplay`), `CatalogTimeline`, `TimeSeries` y `OrbitElements`, con rutas `GET /api/catalog/layers`, `GET /api/catalog/timeline`, `GET /api/catalog/files/{path}` (Range), `GET /api/series`, `GET /api/gamc/wms`, `GET /api/orbit/nisar` y `GET /api/terrain/...` (quantized-mesh).
