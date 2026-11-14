# 05 · Flujo de Trabajo Spec-Driven Development (OpenSpec)

Para coordinar el desarrollo paralelo entre **Frontend (Angular 22)**, **Backend TS (NestJS)**, **Pipeline Python (FastAPI)** y los **2 Harnesses** sin romper contratos ni inventar mocks, utilizamos **OpenSpec (`1.15.0`)**.

---

## 1. ¿Por qué OpenSpec?

* **Contratos antes de código:** Definimos primero el *qué* y los esquemas de entrada/salida entre TS, Python y Angular antes de implementar.
* **Cambios incrementales:** Cada feature o módulo entra como un *change* aislado en `openspec/changes/<nombre-cambio>/`.
* **Reglas persistentes:** La configuración en [`openspec/config.yaml`](../openspec/config.yaml) recuerda automáticamente a todos los colaboradores y agentes los constraints clave (cero mocks, 12-Factor, SOLID, 3 archivos en Angular, madurez de datos NISAR).

---

## 2. Ciclo de Trabajo por Módulo o Feature

1. **Proponer cambio (`proposal.md`):** Qué problema resuelve, qué módulos de `gateway-ts` / `compute-py` / `frontend` toca, y qué datos reales de `data-map.json` usa.
2. **Especificar requisitos (`specs/`):** Criterios verificables con palabras clave RFC 2119 (`SHALL` / `MUST`) — por ejemplo: *"El módulo `gamc-proxy` MUST inyectar `GAMC_WMS_KEY` en servidor y SHALL NOT exponerla en respuestas al cliente"*.
3. **Diseñar (`design.md`):** Elección arquitectónica del módulo (3 capas vs Hexagonal), trade-offs y contratos JSON/OpenAPI.
4. **Planificar tareas (`tasks.md`):** Tareas pequeñas y verificables contra endpoints/archivos reales.
5. **Implementar y archivar:** Una vez validado contra datos reales, se archiva el cambio (`openspec archive`) actualizando la especificación viva en `openspec/specs/`.

---

## 3. Comandos Útiles de OpenSpec

```bash
# Ver estado de cambios y specs activas
openspec list
openspec list --specs

# Validar especificaciones y cambios
openspec validate --all --no-interactive

# En el IDE / agente con las integraciones instaladas en .agents/:
# /opsx-propose "Descripción del módulo o feature"
# /opsx-apply
# /opsx-archive
```

---

## 4. Primeros Cambios Sugeridos (Orden Recomendado)

1. `01-data-ingestion-and-harness-analyst`: Autenticación Earthdata, manifiestos reales en `data/manifests/` y **Harness 1** validando `data-map.json`.
2. `02-geoprocessing-cog-zarr-pmtiles`: Conversión de escenas reales a `COG`, `Zarr`, `PMTiles` y `Parquet/CSV`.
3. `03-gamc-wms-proxy-and-catalog`: `gamc-proxy` + `catalog-tiles` en `gateway-ts`.
4. `04-harness-interpreter-and-llm`: **Harness 2** generando el dataset didáctico en `data/datasets/` + `llm-advisor`.
5. `05-risk-assessment-and-angular-app`: Dominio `risk-assessment` + vistas Angular 22 (`basin-map`, `temporal-lab`, `risk-dashboard`, `didactic-insights`, `data-provenance`).
