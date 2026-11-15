## mapa json con todas las urls y accesos que encontramos:

./data-map.json

### backend
- define la arquitectura y modulos, usaremos python con fast api para modulos que lo requieran, servicios de ia externo, analisis y procesamiento de datos.

### frontend
- para el frontend usaremos la estructura core, feature, layout y shared. para cada feature tendremos 3 archivos, .ts, .scss, .html. 

- angular 22 con signals de forma nativa, ngrx si es necesario, standalone components, pipes, lazy loading.

- patrones como dump smart component.

### integración del harness (Harness Unificado)

Ahora se define **1 solo Harness Integral** con un pipeline determinista en Python y **1 sola Skill de Inteligencia Artificial para Claude Code**:

1. **Capa Determinista (Python / uv):**
   - **Catálogo y Consulta (`input_data.py` / `test_aws_nisar.py`):** Valida STS en AWS y consulta en vivo NASA CMR para recuperar gránulos y URIs S3/HTTPS.
   - **Exportación Multi-Formato (`export_nisar_formats.py`):** Genera GeoTIFF (`.tif`), PNG en dB, Falso Color RGB, KML 3D y GeoJSON en `output/formats/`.
   - **Curación Física y Matemáticas SAR (`curate_sar_physics.py`):** Filtra ruido de moteado (speckle), corrige píxeles inválidos, calcula RVI, CPR y normalización angular, generando `output/curated_sar_metrics.json`.

2. **Capa Cognitiva · Única Skill de Claude Code (`nisar-didactic-interpreter`):**
   - Recibe las métricas físicas curadas y los formatos derivados.
   - Traduce la física radar en Banda L a explicaciones accesibles, correlaciona el contexto de la Cuenca de Cochabamba (Parque Tunari, Río Rocha, Laguna Alalay) y genera los payloads en Markdown y JSON para la UI en Angular.

## constraints

- respetar la estructura de carpetas y 3 archivos del frontend

- usar solid para el backend

- 12 factor apps para todo el proyecto

- monolito modular, respetar los modulos.

- tu no debes hacer los commits