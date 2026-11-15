## ADDED Requirements

### Requirement: Vista de planeta con motor 3D aislado
La feature `features/orbit-view/` SHALL renderizar el globo con CesiumJS a través de `core/globe-engine/` y del servicio adaptador `core/services/globe-engine.service.ts`. CesiumJS y `satellite.js` MUST cargarse solo al entrar a `orbit-view` o a la vista de deformación 3D, y el motor MUST destruirse (entidades, workers, contexto WebGL) al salir de la ruta.

#### Scenario: Entrar a la vista de planeta
- **WHEN** el usuario navega a `orbit-view`
- **THEN** se descarga Cesium en ese momento y se muestra el globo con imagen base de NASA GIBS

#### Scenario: Salir de la vista de planeta
- **WHEN** el usuario pasa de `orbit-view` a `basin-map`
- **THEN** el motor Cesium se destruye antes de crear el motor MapLibre y nunca hay dos contextos 3D activos a la vez

### Requirement: Sin Cesium ion ni credenciales
El motor 3D MUST NOT usar Cesium ion ni ningún token. La imagen base SHALL provenir de NASA GIBS (WMTS público) con su URL declarada en `runtime-config.json`. El terreno de la cuenca SHALL provenir del tileset quantized-mesh servido por `gateway-ts`; fuera de la cuenca SHALL usarse el elipsoide.

#### Scenario: Revisión de configuración
- **WHEN** se inspecciona el código y la configuración del frontend
- **THEN** no existe `Ion.defaultAccessToken` ni ninguna llamada a `ion.cesium.com`

#### Scenario: Terreno no disponible
- **WHEN** el backend todavía no publica el tileset quantized-mesh
- **THEN** `orbit-view` funciona sobre el elipsoide y solo la vista de deformación 3D indica que el terreno no está disponible

### Requirement: Posición del satélite calculada en tiempo real
El frontend SHALL obtener los elementos orbitales de NISAR desde `GET /api/orbit/nisar` y SHALL calcular la posición con `satellite.js` (SGP4) sincronizada con la hora actual. El frontend MUST NOT llamar a CelesTrak ni a ningún servicio orbital externo.

#### Scenario: Ver el satélite
- **WHEN** el usuario abre `orbit-view`
- **THEN** NISAR aparece a su altitud calculada y se desplaza en tiempo real sobre el globo

#### Scenario: Acelerar el tiempo
- **WHEN** el usuario acelera el reloj de la vista
- **THEN** el satélite y su traza avanzan según la velocidad elegida y un control permite volver a "ahora"

### Requirement: Órbita, traza y franja de observación
`orbit-view` SHALL dibujar la órbita del satélite (una vuelta hacia atrás y una hacia adelante), su traza sobre el suelo y la franja aproximada que observa el radar (~240 km de ancho). La franja MUST mostrarse rotulada como aproximada. Las predicciones de varias órbitas MUST calcularse en `core/workers/orbit.worker.ts`.

#### Scenario: Trayectoria visible
- **WHEN** el satélite está en pantalla
- **THEN** se ven su órbita, su traza sobre el suelo y la franja aproximada sin bloquear la interacción

### Requirement: Próximo paso sobre Cochabamba
El frontend SHALL calcular en un worker los pasos de NISAR sobre `area_of_interest.core_city` en las próximas 48 horas y SHALL mostrar el próximo con cuenta regresiva en el componente dumb `shared/components/pass-countdown/` (3 archivos).

#### Scenario: Cuenta regresiva
- **WHEN** el usuario abre `orbit-view`
- **THEN** ve la fecha y hora local del próximo paso sobre Cochabamba y el tiempo restante actualizándose cada segundo

### Requirement: Honestidad del dato orbital
La UI MUST indicar que la posición es calculada a partir de elementos orbitales públicos (no telemetría) y MUST mostrar la antigüedad del TLE (`epoch`). La UI MUST aclarar que un paso del satélite no garantiza que se haya tomado una imagen. Si el TLE tiene más de 3 días, SHALL mostrarse una advertencia.

#### Scenario: TLE antiguo
- **WHEN** el `epoch` del TLE recibido tiene más de 3 días
- **THEN** la vista muestra una advertencia de posición posiblemente imprecisa

#### Scenario: Paso sin adquisición
- **WHEN** se muestra el próximo paso sobre Cochabamba
- **THEN** el texto aclara que es un paso orbital previsto y no una adquisición confirmada

### Requirement: Enlace con los datos reales
`orbit-view` SHALL mostrar la última adquisición real de Cochabamba según `CatalogTimeline`, con su fecha y su madurez, y SHALL permitir pasar a `basin-map` sobre Cochabamba conservando idioma y estado en la URL.

#### Scenario: Del planeta a la cuenca
- **WHEN** el usuario elige "ver Cochabamba" desde `orbit-view`
- **THEN** la cámara desciende hacia la cuenca y la app navega a `basin-map` con la última adquisición seleccionada

### Requirement: Vista 3D de deformación
El motor 3D SHALL mostrar el desplazamiento LoS de GUNW sobre el terreno quantized-mesh de la cuenca, coloreado con el `display` del catálogo (escala definida por el backend) mediante un worker que pinta el COG en un canvas usado como imagen por Cesium. La vista MUST mostrar la madurez y el par de fechas del interferograma.

#### Scenario: Deformación en el Tunari
- **WHEN** el usuario abre la vista de deformación con un par GUNW
- **THEN** ve el desplazamiento en mm sobre el relieve 3D con su leyenda, madurez y fechas del par
