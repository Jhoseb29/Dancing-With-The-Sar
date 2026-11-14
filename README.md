# Dancing with the SARs — Alerta Temprana de Riesgos en Cuencas (Cochabamba)

> **NASA Space Apps Challenge 2026** · Sede Cochabamba, Bolivia  
> Desafío global: [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/?tab=details) · Enfoque local: **Proyecto 02 — Alerta Temprana de Riesgos en Cuencas**

---

## 1. ¿Qué estamos construyendo?

Una plataforma interactiva de monitoreo multitemporal y alerta temprana para las cuencas del área metropolitana de Cochabamba (**Cordillera del Tunari al norte** y **valle del Río Rocha / zona sur**), combinando **datos satelitales reales** (radar SAR L-band **NISAR**, lluvia **GPM IMERG**, elevación **Copernicus DEM**, y opcionalmente **OPERA Sentinel-1 / HLS / JRC Water**) con **cartografía e incidentes reales del GAMC** (servicios WMS/GeoServer municipales).

La solución busca responder tres preguntas críticas para tomadores de decisiones, equipos técnicos y ciudadanía:
1. **¿Dónde está cambiando la superficie?** (humedad de suelo, anegamiento/inundación en zona sur, pérdida de cobertura vegetal y deformación milimétrica/centimétrica en laderas del Tunari).
2. **¿Por qué ocurre el cambio?** (correlación entre precipitación acumulada, pendiente/drenaje, respuesta polarimétrica SAR `HHHH`/`HVHV` y pérdida de coherencia InSAR).
3. **¿Qué significa para la cuenca y su población?** (traducción automática, validada y didáctica mediante dos *Harnesses* de IA/análisis respaldados por evidencia real).

---

## 2. Principios y Restricciones del Proyecto

1. **Cero Mocks (Datos 100% Reales):** Todo producto mostrado o analizado debe provenir de fuentes reales definidas en [`data-map.json`](./data-map.json). Toda capa derivada de NISAR debe etiquetar explícitamente su nivel de madurez (`BETA`, `PROVISIONAL` o `VALIDATED`) y `track/frame`.
2. **Monolito Modular Políglota (`./backend`) + SPA (`./frontend`):**
   * Un único repositorio (*monorepo*) para iterar rápido en la hackathon con límites modulares estrictos.
   * **TypeScript (NestJS)** para gateway/BFF, proxy seguro del GAMC, catálogo geoespacial y dominio de evaluación de riesgos.
   * **Python (FastAPI)** para ingesta NASA Earthdata/ASF, procesamiento geoespacial (**COG + Zarr + PMTiles**), conexión con LLMs externos y los **2 Harnesses** (como módulos del backend).
   * **Angular 22** en `./frontend` con Signals nativos, Standalone Components, Pipes, Lazy Loading, patrón Smart/Dumb y estructura estricta `core/`, `layout/`, `shared/`, `features/` (3 archivos por componente: `.ts`, `.html`, `.scss`).
3. **SOLID & 12-Factor App:** Inyección de dependencias e inversión de puertos en módulos de dominio; configuración, secretos (`EARTHDATA_*`, `GAMC_WMS_KEY`, `LLM_*`) y servicios externos desacoplados exclusivamente vía variables de entorno. **Nunca subir `.env` ni credenciales al repositorio.**
4. **Spec-Driven Development (SDD) con OpenSpec:** Antes de escribir código de cualquier módulo o feature, definimos el contrato y alcance en [`openspec/`](./openspec/config.yaml).
5. **Regla de Git:** Los agentes de IA tienen prohibido ejecutar `git commit` o `git push`, y `data/raw/` nunca se sube a Git.

---

## 3. Estructura del Repositorio

```text
.
├── README.md                  # Este documento (punto de entrada del equipo)
├── project_details.md         # Requisitos y constraints base del MVP
├── data-map.json              # Mapa verificado de fuentes NASA, Copernicus y GAMC
├── .gitignore                 # Bloquea .env, data/raw/, binarios pesados y caches
├── docs/                      # Documentación técnica de arquitectura y pipeline
│   ├── 01-architecture-overview.md
│   ├── 02-backend-modules.md
│   ├── 03-frontend-architecture.md
│   ├── 04-data-pipeline-and-harnesses.md
│   └── 05-openspec-workflow.md
├── openspec/                  # Especificaciones SDD (OpenSpec 1.15.0)
├── backend/                   # Monolito modular (TypeScript + Python)
│   ├── gateway-ts/            # Runtime NestJS (BFF, Proxy GAMC, Catálogo, Riesgo)
│   ├── compute-py/            # Runtime FastAPI (Ingesta, COG/Zarr/PMTiles, LLM, Harnesses 1 y 2)
│   └── shared/                # Contratos OpenAPI / JSON Schemas compartidos TS <-> Py
├── frontend/                  # SPA Angular 22 (TypeScript)
│   └── src/app/
│       ├── core/              # Servicios singleton, config, estado global con Signals
│       ├── layout/            # Shell principal, navegación, paneles base
│       ├── shared/            # Dumb components reutilizables, pipes, directivas, modelos
│       └── features/          # Módulos funcionales lazy-loaded (.ts, .html, .scss)
└── data/                      # Almacenamiento local de datos geoespaciales (ver .gitignore)
    ├── manifests/             # CSVs ligeros de búsqueda y trazabilidad
    ├── raw/                   # Descargas/subsets HDF5 y NetCDF (NUNCA commitear)
    ├── processed/             # Productos cloud-native: cog/, zarr/, pmtiles/, tables/
    └── datasets/              # Datasets interpretados y entrenados por Harness 2
```

---

## 4. Guía de Lectura para el Equipo

* **Arquitectura general, 12-Factor, SOLID y trade-offs:** [`docs/01-architecture-overview.md`](./docs/01-architecture-overview.md)
* **Diseño de módulos del Backend y Harnesses:** [`docs/02-backend-modules.md`](./docs/02-backend-modules.md)
* **Estándares y estructura del Frontend Angular 22:** [`docs/03-frontend-architecture.md`](./docs/03-frontend-architecture.md)
* **Pipeline real COG + Zarr + PMTiles y flujo Harness 1 -> Harness 2:** [`docs/04-data-pipeline-and-harnesses.md`](./docs/04-data-pipeline-and-harnesses.md)
* **Cómo trabajaremos con OpenSpec (SDD):** [`docs/05-openspec-workflow.md`](./docs/05-openspec-workflow.md)
