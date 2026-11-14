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
    │   │   └── state/
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
    │       └── data-provenance/
    └── assets/
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
| **`temporal-lab`** | Laboratorio multitemporal: comparación época seca (`2026-06-17`–`2026-10-20`, `PROVISIONAL`) vs inicio de lluvias (`2026-10-21+`, `VALIDATED`), animación sobre cubos **Zarr** y gráfica sincronizada con lluvia **GPM IMERG**. | Cubos Zarr GCOV, series CSV/Parquet GPM IMERG. |
| **`risk-dashboard`** | Panel de alerta temprana por cuenca/distrito: diferencia riesgo en **laderas del norte (Tunari: deslizamientos/torrenteras)** vs **valle sur (Albarrancho/Rocha: inundación/saturación)**. | `risk-assessment` + `Emergencias` GAMC + métricas derivadas. |
| **`didactic-insights`** | Visualización didáctica e interactiva de los resultados del **Harness 2** (lenguaje claro para ciudadanía, defensa civil y técnica) + consultas asistidas al módulo `llm-advisor`. | Dataset entrenado/interpretado de `harness-interpreter` + `llm-advisor`. |
| **`data-provenance`** | Transparencia científica: manifiestos reales, score y juicio del **Harness 1**, estado de calibración CRID, `track/frame` activo y advertencias de brechas (`2026-07-27` a `2026-08-10`). | Manifiestos CSV + artefactos de evaluación de `harness-analyst`. |
