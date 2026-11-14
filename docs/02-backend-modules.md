# 02 · Módulos del Backend (`./backend`)

El backend es un **Monolito Modular** dividido en dos runtimes complementarios que comparten contratos en [`backend/shared/`](../backend/shared/):

1. **`backend/gateway-ts/` (TypeScript · NestJS):** Punto de entrada único para Angular 22, seguridad, proxy WMS del GAMC, catálogo de tiles/cubos y reglas de dominio de riesgo territorial.
2. **`backend/compute-py/` (Python 3.10+ · FastAPI):** Motor de ingesta NASA/Copernicus, procesamiento geoespacial (`COG`, `Zarr`, `PMTiles`), integración LLM externa y los **2 Harnesses** (como módulos propios del backend).

> **Regla de aislamiento:** Ningún módulo puede importar archivos internos (infraestructura/entidades privadas) de otro módulo. La comunicación entre módulos dentro del mismo runtime ocurre mediante sus fachadas/interfaces públicas; entre TS y Python ocurre mediante contratos HTTP/JSON Schema definidos en `backend/shared/`.

---

## 1. Runtime TypeScript (`backend/gateway-ts/`)

```text
backend/gateway-ts/
└── src/
    ├── config/          # Validación de env vars (12-Factor Factor III)
    └── modules/
        ├── orchestrator/
        ├── gamc-proxy/
        ├── catalog-tiles/
        └── risk-assessment/
```

### 1.1 `orchestrator` · Patrón: **3 Capas (Facade / BFF)**
* **Responsabilidad:** Exponer la API unificada para el frontend Angular 22, coordinar flujos compuestos (p. ej. pedir mapa de cuenca + series temporales + explicación didáctica de Harness 2) y despachar trabajos hacia `compute-py`.
* **Justificación del patrón:** Actúa como coordinador de casos de uso hacia HTTP/SSE; una arquitectura de 3 capas (`controllers/` -> `services/` -> `clients/`) evita duplicar entidades de dominio.

### 1.2 `gamc-proxy` · Patrón: **3 Capas (`controllers/`, `services/`, `infrastructure/`)**
* **Responsabilidad:** Proxificar las operaciones WMS 1.1.1 de `https://serviciosgamc.cochabamba.bo/api/gs/wms`:
  * `GetMap` (PNG transparente EPSG:3857)
  * `GetLegendGraphic` (WMS 1.0.0 PNG)
  * `GetFeatureInfo` (`application/json` al hacer clic sobre el mapa)
* **Seguridad crítica:** Inyecta `GAMC_WMS_KEY` desde el entorno del servidor (`.env`). **La llave jamás viaja al frontend.**
* **Servicios mapeados en `data-map.json`:** `Cuencas UH 8`, `Cuencas UH 7`, `Cuencas de Influencia`, `Drenaje e Influencia`, `Cota 2750`, `Limite Distritos`, `Emergencias`.
* **Justificación del patrón:** Es un adaptador HTTP/WMS con caché ligera de leyendas y metadatos; 3 capas es directo y mantenible.

### 1.3 `catalog-tiles` · Patrón: **3 Capas (`controllers/`, `services/`, `infrastructure/`)**
* **Responsabilidad:** Exponer el inventario de capas reales generadas en `data/processed/` (COGs, cubos Zarr, archivos PMTiles y series CSV/Parquet) junto con su metadato obligatorio: `maturity` (`BETA` | `PROVISIONAL` | `VALIDATED`), `track`, `frame`, `direction`, `crid`, `acquisition_date`.
* **Entrega eficiente:** Soporta peticiones HTTP `Range` (206 Partial Content) para **PMTiles** y **COGs**, y delega slicing dinámico de **Zarr** o renders bajo demanda a `compute-py`.

### 1.4 `risk-assessment` · Patrón: **Arquitectura Hexagonal (`domain/`, `application/`, `ports/`, `adapters/`)**
* **Responsabilidad:** Evaluar el estado de riesgo por cuenca y distrito (Cochabamba norte/Tunari: deslizamientos y torrenteras; valle sur/Albarrancho: saturación e inundaciones) cruzando:
  * Señales físicas de SAR (anomalías `gamma0` en `GCOV`, pérdida de coherencia y desplazamiento LoS en `GUNW`, humedad `SME2`/índice derivado).
  * Lluvia acumulada (`GPM IMERG`) y pendiente/drenaje (`Copernicus DEM`).
  * Contexto municipal (`GAMC`: `Emergencias`, `Cota 2750`, `Cuencas`).
* **Regla de integridad científica:** Impide mezclar cuantitativamente escenas `BETA` con `PROVISIONAL`/`VALIDATED` sin emitir bandera explícita de incompatibilidad de `CRID`.
* **Justificación del patrón:** Contiene reglas de negocio críticas que deben poder probarse de forma aislada respecto a fuentes HTTP y almacenamiento.

---

## 2. Runtime Python (`backend/compute-py/`)

```text
backend/compute-py/
└── src/
    ├── config/          # Configuración Pydantic Settings (12-Factor)
    └── modules/
        ├── ingestion/
        ├── geoprocessing/
        ├── llm-advisor/
        ├── harness-analyst/       # HARNESS 1
        └── harness-interpreter/   # HARNESS 2
```

### 2.1 `ingestion` · Patrón: **Arquitectura Hexagonal (`domain/`, `application/`, `ports/`, `adapters/`)**
* **Responsabilidad:** Autenticarse contra NASA Earthdata (`earthaccess` vía `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` o `~/.netrc`), consultar `asf_search` / CMR sobre `area_of_interest.basin` (`[-66.536394, -17.870027, -65.574648, -17.186852]`), generar manifiestos CSV en `data/manifests/` **antes** de descargar, seleccionar un único `track/frame` consistente y hacer streaming/subsetting hacia `data/raw/`.
* **Justificación del patrón:** Desacopla el protocolo de búsqueda/descarga (NASA CMR, ASF, AWS S3 público para Copernicus DEM, HTTP para JRC) de las reglas de selección de granulos y control de tamaño (~5 GB guard).

### 2.2 `geoprocessing` · Patrón: **Pipeline + Hexagonal (`domain/`, `pipelines/`, `ports/`, `adapters/`)**
* **Responsabilidad:** Transformar datos crudos en productos *cloud-native* listos para visualización y análisis rápido:
  * **COG (`data/processed/cog/`):** `GCOV` en dB (`HHHH`, `HVHV`, etc.), desplazamiento LoS y coherencia `GUNW`, `DEM` + pendiente + terrain-RGB.
  * **Zarr (`data/processed/zarr/`):** Cubos `(time, y, x)` para consultas de series temporales por píxel y animaciones.
  * **PMTiles (`data/processed/pmtiles/`):** Capas vectoriales/zonales optimizadas para MapLibre GL.
  * **Tables (`data/processed/tables/`):** Series diarias `GPM IMERG` y estadísticas agregadas por cuenca/distrito en Parquet/CSV.

### 2.3 `llm-advisor` · Patrón: **Arquitectura Hexagonal (`domain/`, `application/`, `ports/`, `adapters/`)**
* **Responsabilidad:** Conector limpio hacia servicios LLM externos mediante un puerto `LLMProviderPort`. Recibe contexto estructurado y verificado (nunca inventa cifras) para asistir tanto a los Harnesses como a consultas del usuario final.

### 2.4 `harness-analyst` (Harness 1) · Patrón: **Hexagonal + Agentic Skills**
* **Responsabilidad:** Módulo analista que inspecciona `data-map.json` y los datos reales obtenidos, **crea skills** con **scripts ejecutables** propios de análisis y validación, ejecuta comprobaciones sobre los datos reales (cobertura AOI, short names, gaps temporales, consistencia `track/frame`, madurez), asigna un **score** y emite un **juicio estructurado** para alimentar al Harness 2.
* *(Ver detalle completo en [`04-data-pipeline-and-harnesses.md`](./04-data-pipeline-and-harnesses.md)).*

### 2.5 `harness-interpreter` (Harness 2) · Patrón: **Hexagonal + Dataset Feedback Loop**
* **Responsabilidad:** Consume el output y score del Harness 1, genera explicaciones **didácticas y accesibles** adaptadas por perfil de usuario (ciudadanía, municipio/defensa civil, técnico), refina/entrena su comportamiento con la data real procesada y persiste el resultado en un **dataset estructurado** en `data/datasets/`.
* *(Ver detalle completo en [`04-data-pipeline-and-harnesses.md`](./04-data-pipeline-and-harnesses.md)).*

---

## 3. Contratos Compartidos (`backend/shared/`)

* `backend/shared/contracts/`: Esquemas JSON Schema / OpenAPI que definen las estructuras de intercambio entre `gateway-ts` y `compute-py` (manifiestos, solicitudes de ingesta, resultados de serie temporal Zarr, salidas del Harness 1 y datasets del Harness 2).
* `backend/shared/schemas/`: Definiciones canónicas de metadatos geoespaciales (`maturity`, `bbox`, `track_frame`, `risk_level`).
