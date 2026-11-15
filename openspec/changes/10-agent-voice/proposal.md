## Why

Fase 4 de la hoja de ruta del agente: además del teclado, el usuario debe poder **hablar** con el agente y **escucharlo**, de forma natural y fluida (saludo, explicación de lo que se ve, preguntas), e interrumpirlo cuando quiera.

## Investigación de proveedores (2026-11-14)

Con la `GEMINI_API_KEY` del proyecto:

| Prueba | Resultado |
| :--- | :--- |
| Modelos de la cuenta con texto→voz | Ninguno dedicado a TTS en `models.list()` |
| `generate_content` + `speech_config` (hydrogen, omni) | `400`: el campo `speechConfig` no existe en esta API |
| `gemini-omni-flash-preview` | Solo Interactions API (v1beta); pidiendo `audio` devolvió **un video MP4 de 5,8 MB en 44 s** |

Conclusión: hoy Gemini no ofrece en esta cuenta una voz utilizable para conversación. Se usa la **Web Speech API del navegador** (reconocimiento y síntesis), detrás de interfaces que permiten conectar un proveedor con key en el backend más adelante sin tocar el agente.

## What Changes

- `core/voice/` (TS puro):
  - `speech-engines.ts`: reconocimiento de voz del navegador (`SpeechRecognition`, texto parcial en vivo y resultado final) y síntesis por frases;
    elige la mejor voz disponible para el idioma (prefiere voces "Natural"/"Online"/"Google").
  - Interfaces `SpeechInputEngine` / `SpeechOutputEngine` para cambiar de proveedor.
- `core/services/voice.service.ts`: estado como Signals (soporte, escuchando, hablando, texto parcial), interrupción (barge-in) y modo manos libres.
- `SceneState.panels.voice`: `{ output: boolean, handsFree: boolean }` (shadow: el usuario y el agente pueden activarlo).
- `agent-dock`: botón de micrófono, texto parcial en vivo, interruptores "leer respuestas" y "manos libres", aviso de privacidad y de navegador sin soporte.
- Prompt del agente: respuestas pensadas para leerse en voz alta.

## Capabilities

### New Capabilities
- `agent-voice`: conversación por voz con el agente (entrada, salida, interrupción, manos libres).

### Modified Capabilities
- `scene-shadow` (07): `/panels/voice/output`, `/panels/voice/handsFree`.
- `agent-dock` (08): controles de voz.

## Impact

- **Frontend:** `core/voice/`, `core/services/voice.service.ts`, `layout/agent-dock`, i18n, schema del shadow.
- **Backend:** solo el prompt (texto apto para voz). El protocolo WebSocket no cambia: la voz se convierte en `user.text` y las respuestas `agent.text` se leen en el navegador.
- **Privacidad:** el reconocimiento de voz del navegador envía el audio al servicio de voz del navegador (Google en Chrome, Microsoft en Edge). La UI lo indica antes de usar el micrófono. El micrófono solo se activa por acción del usuario.
- **Compatibilidad:** reconocimiento en Chrome, Edge y Safari; Firefox no lo soporta (la UI lo dice y sigue funcionando por teclado). Síntesis en todos los navegadores modernos.
- **Sin keys nuevas.**

## Actualización tras prueba con usuario (2026-11-14)

El reconocimiento de voz del navegador **falló en la máquina del usuario** con el error `network` (con internet funcionando): depende de un servicio externo del navegador que no siempre responde. Se cambia el motor de entrada:

- **Entrada de voz:** el navegador **graba** (MediaRecorder, Opus) con detección de silencio local y envía el audio por el WebSocket (`user.audio`). El backend lo **transcribe con Gemini** (`GEMINI_STT_MODEL`, por defecto `gemini-3.5-flash-lite`) y devuelve `user.transcript`; luego sigue el mismo turno que el texto. La key queda en el servidor.
- **Respaldo:** si el navegador no puede grabar, se usa su reconocimiento de voz.
- **Salida de voz:** sin cambios (síntesis del navegador).
- **Privacidad:** el aviso indica que el audio va al servidor del proyecto y a Gemini (Google) para transcribirse, y que no se guarda.
