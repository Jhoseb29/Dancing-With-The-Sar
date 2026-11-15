## ADDED Requirements

### Requirement: Configuración de UI en JSON
Rutas, lugares, presets de capas y recorridos de cámara SHALL definirse en `frontend/src/assets/config/{routes,places,layers,camera-tours}.json`, cada uno conforme a su schema en `backend/shared/schemas/`. El código MUST NOT contener listas de lugares, capas o recorridos.

#### Scenario: Agregar un lugar
- **WHEN** se agrega un lugar con bbox a `places.json`
- **THEN** aparece en el buscador y el agente puede usarlo sin cambiar código

### Requirement: Rutas declaradas
`routes.json` SHALL listar cada vista con `id`, `path`, clave i18n, `engine` y una descripción para el agente. Al arrancar en desarrollo, la app SHALL advertir en consola si alguna ruta de `routes.json` no tiene `loadChildren` registrado o viceversa.

#### Scenario: Ruta sin componente
- **WHEN** `routes.json` declara `temporal` pero el registro de rutas no lo tiene
- **THEN** la consola de desarrollo muestra una advertencia con el `id`

### Requirement: Buscador de lugares
La barra superior SHALL tener un buscador sobre `places.json` que ignore acentos y mayúsculas y busque en nombres y alias en español e inglés. Elegir un resultado SHALL aplicar `/search/selectedPlaceId` y `/camera/placeId`.

#### Scenario: Buscar sin acento
- **WHEN** el usuario escribe "cochabamba"
- **THEN** aparecen "Cochabamba (área urbana)" y la cuenca, y al elegir uno la cámara vuela hasta su bbox

### Requirement: Recorridos de cámara
`camera-tours.json` SHALL definir recorridos como pasos (`placeId` o destino, altitud, duración, pausa). El motor 3D SHALL ejecutarlos al aplicar `/camera/tourId` y SHALL cancelarlos (`/camera/tourId = null`) ante interacción manual.

#### Scenario: Recorrido de bienvenida
- **WHEN** se aplica `/camera/tourId = 'welcome'`
- **THEN** la cámara va del globo a Bolivia y luego a Cochabamba según los pasos del JSON
