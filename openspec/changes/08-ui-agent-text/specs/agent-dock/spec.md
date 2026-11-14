## ADDED Requirements

### Requirement: Panel del agente
`layout/agent-dock` (3 archivos) SHALL estar disponible en todas las vistas, abierto o cerrado según `/panels/agentDock` del `SceneState`. SHALL mostrar la conversación como transcripción de "radio de misión" (estilo del sistema de diseño), un campo de texto y el estado de conexión.

#### Scenario: Abrir el panel
- **WHEN** el usuario pulsa el botón del agente
- **THEN** se aplica `/panels/agentDock = 'open'`, se abre la sesión WebSocket y aparece el saludo

### Requirement: Aplicar los parches del agente
El cliente SHALL aplicar cada `scene.patch` recibido con `SceneStore.patch({ origin: 'agent', baseVersion, ops })` y SHALL responder `scene.patch.result` con `ok`, `reason`, la versión y el estado reportado tras el cambio.

#### Scenario: Parche del agente
- **WHEN** llega `scene.patch` con `/route = basin`
- **THEN** la app navega a la cuenca y responde `scene.patch.result` con `ok: true`

### Requirement: Accesibilidad y estados
El panel SHALL ser operable con teclado (Enter envía, Escape cierra), anunciar respuestas nuevas con `aria-live="polite"` y mostrar estados de conexión, "pensando…" y error sin bloquear la página.

#### Scenario: Backend apagado
- **WHEN** el servicio del agente no responde
- **THEN** el panel muestra "Agente no disponible" y el resto de la app sigue funcionando
