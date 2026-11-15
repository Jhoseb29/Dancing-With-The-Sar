## ADDED Requirements

### Requirement: Motor geoespacial desacoplado de Angular
El frontend SHALL implementar el renderizado del mapa en `frontend/src/app/core/map-engine/` como código TypeScript sin dependencias de `@angular/*`. Los componentes y features MUST NOT instanciar `maplibre-gl` ni `deck.gl` directamente; SHALL interactuar con el motor exclusivamente mediante un servicio adaptador en `core/services/`.

#### Scenario: Una feature muestra una capa
- **WHEN** `basin-map` necesita mostrar la capa GCOV `HVHV` de una fecha
- **THEN** llama al servicio adaptador del motor con un descriptor de capa (id del catálogo, fecha, polarización)
- **AND** ningún archivo dentro de `features/` importa `maplibre-gl` o `@deck.gl/*`

#### Scenario: El motor no depende de Angular
- **WHEN** se revisan los imports de `core/map-engine/`, `core/globe-engine/`, `core/data-access/` y `core/workers/`
- **THEN** ningún archivo importa `@angular/*`

### Requirement: Vista de globo y terreno
El motor SHALL usar MapLibre GL JS con proyección `globe` para la vista planetaria y transicionar a la vista de cuenca (`area_of_interest.core_city`) al acercarse. El relieve SHALL provenir del terrain-RGB del Copernicus DEM servido por `catalog-tiles`. deck.gl SHALL integrarse como overlay intercalado (`MapboxOverlay` con `interleaved: true`).

#### Scenario: Apertura inicial
- **WHEN** el usuario abre `basin-map`
- **THEN** el mapa inicia encuadrado en el bbox `core_city` de `data-map.json` con terreno 3D activo

#### Scenario: Alejar hasta el planeta
- **WHEN** el usuario aleja el zoom por debajo del nivel regional
- **THEN** el mapa se muestra como globo sin recargar capas ni reiniciar el motor

### Requirement: Fuentes de datos solo vía gateway
Toda petición de productos del proyecto (COG, PMTiles, WMS, series, tablas, órbita, terreno) MUST dirigirse a rutas de `gateway-ts`. Los motores MUST NOT contener URLs de `serviciosgamc.cochabamba.bo`, de NASA/ASF, de CelesTrak ni ninguna credencial. Como única excepción, los motores MAY cargar mapas base públicos y sin credenciales (NASA GIBS) cuyas URLs estén declaradas en `runtime-config.json`.

#### Scenario: Capa WMS del GAMC
- **WHEN** el motor muestra la capa `Emergencias`
- **THEN** las teselas se piden a `/api/gamc/...` con el `service_id` como parámetro y sin `key`

#### Scenario: Revisión de secretos
- **WHEN** se busca `GAMC_WMS_KEY`, `EARTHDATA`, `celestrak` o el dominio `serviciosgamc` en el código compilado del frontend
- **THEN** no hay coincidencias

#### Scenario: Mapa base público
- **WHEN** `orbit-view` carga la imagen Blue Marble
- **THEN** la URL de NASA GIBS proviene de `runtime-config.json` y la petición no lleva credenciales

### Requirement: Lectura cloud-native en el cliente
`core/data-access/` SHALL leer COG con `geotiff.js` mediante peticiones HTTP Range y PMTiles registrando el protocolo `pmtiles://` en MapLibre. Las series temporales de un píxel o de una cuenca MUST obtenerse ya cortadas desde `orchestrator`; el cliente MUST NOT leer cubos Zarr directamente.

#### Scenario: Zoom sobre un COG
- **WHEN** el usuario hace zoom sobre una capa GCOV
- **THEN** solo se descargan los bytes de las teselas y overviews visibles (respuestas `206 Partial Content`)

#### Scenario: Animación temporal
- **WHEN** `temporal-lab` anima una secuencia de fechas
- **THEN** cada fotograma usa el COG de esa fecha y el motor precarga el COG de la fecha siguiente

#### Scenario: Serie de un píxel
- **WHEN** el usuario hace clic en un punto de `temporal-lab`
- **THEN** el frontend pide la serie a `/api/series` y recibe los valores ya cortados con su unidad y madurez por fecha

### Requirement: Escalas de visualización definidas por el backend
El motor MUST colorear cada capa raster con el `display` (`units`, `value_range`, `colormap`, `nodata`, `defaults`) que entrega `catalog-tiles`. El frontend MUST NOT definir rangos ni paletas propias. Los rasters SHALL llegar como valores físicos (dB, mm, coherencia) y la escala SHALL aplicarse en GPU, de modo que la leyenda, el valor inspeccionado y los controles interactivos usen el mismo metadato.

#### Scenario: Leyenda de una capa
- **WHEN** se muestra la capa GCOV `HVHV`
- **THEN** la leyenda se genera a partir de `display.colormap` y `display.units` del catálogo

#### Scenario: Inspeccionar un valor
- **WHEN** el usuario hace clic sobre un píxel de una capa GCOV
- **THEN** se muestra el valor físico en dB, no un color

#### Scenario: Umbral de agua
- **WHEN** el usuario abre el control de umbral de agua
- **THEN** el valor inicial es `display.defaults.water_threshold_db` del catálogo y al moverlo el mapa se recolorea sin nuevas peticiones

### Requirement: Cálculo raster fuera del hilo principal
Los cálculos por píxel (umbral de agua en dB, diferencia entre fechas, ratio de polarizaciones, reescalado de color) MUST ejecutarse en Web Workers de `core/workers/` o en shaders GPU. El motor SHALL usar WebGPU cuando `navigator.gpu` esté disponible y SHALL degradar a WebGL2 en caso contrario. Los buffers MUST transferirse como `Transferable`, sin copia.

#### Scenario: Cambio de umbral de agua
- **WHEN** el usuario mueve el control de umbral de agua
- **THEN** el mapa se actualiza sin bloquear la interacción (sin tareas largas mayores a 50 ms en el hilo principal)

#### Scenario: Navegador sin WebGPU
- **WHEN** el navegador no expone `navigator.gpu`
- **THEN** el mismo cálculo se resuelve con WebGL2 o el worker y el resultado visual es equivalente

### Requirement: Puente del motor hacia Signals con frecuencia limitada
El servicio adaptador SHALL publicar el estado del motor (vista, capa bajo el cursor, carga) como Signals. Los eventos continuos (movimiento de cámara, hover) MUST limitarse (throttle por `requestAnimationFrame` o al finalizar el gesto) y MUST NOT actualizar Signals en cada frame.

#### Scenario: Arrastrar el mapa
- **WHEN** el usuario arrastra el mapa durante 2 segundos
- **THEN** el signal de vista se actualiza al terminar el gesto (o como máximo una vez por frame), no por cada evento `move`

### Requirement: Etiquetado de madurez y geometría en cada capa NISAR
Toda capa NISAR mostrada por el motor MUST llevar en su descriptor `maturity` (`BETA` | `PROVISIONAL` | `VALIDATED`), `track`, `frame` y `direction`, tomados del catálogo. La UI SHALL mostrarlos junto a la capa.

#### Scenario: Comparación de fechas de distinta madurez
- **WHEN** el usuario compara una fecha `PROVISIONAL` con una `VALIDATED`
- **THEN** ambas capas muestran su badge de madurez y se presenta una advertencia de posible diferencia por `CRID`

### Requirement: Componentes de presentación del motor
`shared/components/map-canvas/` y `shared/components/time-series-chart/` SHALL ser componentes dumb de 3 archivos (`.ts`, `.html`, `.scss`) que reciben datos solo por `input()` y emiten eventos por `output()`. `time-series-chart` SHALL usar uPlot.

#### Scenario: Gráfica sincronizada
- **WHEN** `temporal-lab` pasa a `time-series-chart` la serie GCOV de un píxel y la serie GPM IMERG de la cuenca
- **THEN** la gráfica muestra ambas sobre el mismo eje de tiempo y emite la fecha seleccionada al hacer clic
