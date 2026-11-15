## ADDED Requirements

### Requirement: Hablarle al agente
El panel del agente SHALL ofrecer un botón de micrófono que active el reconocimiento de voz en el idioma activo, muestre el texto parcial en vivo y envíe el resultado final como mensaje del usuario. El micrófono MUST activarse solo por acción del usuario.

#### Scenario: Pregunta por voz
- **WHEN** el usuario pulsa el micrófono y dice "muéstrame las emergencias en Cochabamba"
- **THEN** ve el texto mientras habla y, al terminar, el agente recibe esa frase y actúa igual que si la hubiera escrito

### Requirement: Escuchar al agente
Si `/panels/voice/output` es `true`, cada respuesta del agente SHALL leerse en voz alta en el idioma activo, frase por frase, con la mejor voz disponible del navegador.

#### Scenario: Respuesta leída
- **WHEN** el agente responde con dos frases
- **THEN** ambas se leen en orden y el panel indica que está hablando

### Requirement: Interrumpir
Pulsar el micrófono, escribir o enviar mientras el agente habla o piensa SHALL detener la voz y enviar `user.interrupt`.

#### Scenario: Interrumpir al agente
- **WHEN** el agente está leyendo una respuesta y el usuario pulsa el micrófono
- **THEN** la voz se detiene de inmediato y empieza a escuchar

### Requirement: Manos libres
Si `/panels/voice/handsFree` es `true`, al terminar de leer una respuesta el panel SHALL volver a escuchar automáticamente, siempre que el usuario haya iniciado la conversación por voz en esa sesión.

#### Scenario: Conversación continua
- **WHEN** manos libres está activo y el agente termina de hablar
- **THEN** el micrófono se activa de nuevo y el panel lo indica

### Requirement: Privacidad y compatibilidad
Antes del primer uso del micrófono la UI SHALL indicar que el audio lo procesa el servicio de voz del navegador. Si el navegador no soporta reconocimiento de voz, SHALL indicarlo y mantener el teclado.

#### Scenario: Firefox
- **WHEN** el navegador no expone `SpeechRecognition`
- **THEN** el botón de micrófono aparece deshabilitado con el motivo y el resto funciona por teclado
