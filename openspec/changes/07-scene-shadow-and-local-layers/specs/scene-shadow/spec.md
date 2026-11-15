## ADDED Requirements

### Requirement: SceneState como única fuente de verdad
Todo estado de la UI modificable por el usuario o por el agente (ruta, idioma, cámara, tiempo, capas, búsqueda, paneles) SHALL vivir en un documento JSON `SceneState` dentro de `core/scene/scene.store.ts`, conforme a `backend/shared/schemas/scene-state.schema.json`. Los componentes MUST NOT mantener copias propias de ese estado.

#### Scenario: Cambiar la velocidad del tiempo
- **WHEN** el usuario pulsa "60×" en `orbit-view`
- **THEN** se aplica el parche `{ op: 'replace', path: '/time/speed', value: 60 }` y el motor 3D lee la velocidad del `SceneState`

### Requirement: Cambios solo mediante parches validados
Toda modificación SHALL hacerse con un `ScenePatch` (`origin`, `baseVersion` opcional, `ops` JSON Patch con `replace`/`add`/`remove`). El store MUST rechazar operaciones sobre rutas fuera de la lista blanca. Los parches de origen `agent` MUST validarse contra el JSON Schema y MUST referenciar solo `presetId`, `placeId`, `tourId` y rutas existentes en la configuración. Cada parche aplicado SHALL incrementar `version`.

#### Scenario: Parche de agente inválido
- **WHEN** llega un parche de origen `agent` con `path: '/layers/0/presetId'` y un `value` que no existe en `layers.json`
- **THEN** el parche se rechaza completo, el estado no cambia y se devuelve el motivo

#### Scenario: Ruta no permitida
- **WHEN** un parche intenta modificar `/version`
- **THEN** se rechaza por estar fuera de la lista blanca

#### Scenario: Conflicto con el usuario
- **WHEN** un parche de agente trae `baseVersion` 40, la versión actual es 42 y el usuario cambió `/camera/placeId` en la versión 41
- **THEN** el parche del agente que toca `/camera/placeId` se rechaza y gana la elección del usuario

### Requirement: Estado reportado
Los adaptadores de motor SHALL publicar un estado `reported` con la ruta activa, la cámara real (lon, lat, altitud) y el estado de cada capa (`loading`, `ready`, `error`), como máximo una vez por segundo.

#### Scenario: El agente pregunta qué se ve
- **WHEN** el usuario terminó de mover el mapa
- **THEN** `reported.camera` refleja el centro y la altitud reales tras el gesto

### Requirement: Sincronización con router y URL
La ruta del `SceneState` SHALL coincidir con la ruta del router en ambas direcciones. Los query params `lang`, `place` y `layers` SHALL reflejar el `SceneState` (debounce, `replaceUrl`) y SHALL restaurarlo al abrir un enlace mediante un parche de origen `url`.

#### Scenario: Enlace compartido
- **WHEN** alguien abre `/cuenca?place=cochabamba-city&layers=gamc-emergencias,gamc-cuencas-uh8&lang=en`
- **THEN** ve la cuenca en inglés, encuadrada en el área urbana y con esas dos capas activas

### Requirement: Gancho de desarrollo
En modo desarrollo la app SHALL exponer `window.dwsScene` con `get()`, `reported()` y `patch(ops, origin?)`. El gancho MUST NOT existir en el build de producción.

#### Scenario: Simular al agente
- **WHEN** en la consola de desarrollo se ejecuta `dwsScene.patch([{op:'replace', path:'/route', value:'basin'}], 'agent')`
- **THEN** la app navega a la cuenca exactamente como lo hará el agente
