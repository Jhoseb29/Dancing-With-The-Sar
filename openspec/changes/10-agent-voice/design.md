## Context

El agente (08) conversa por WebSocket con mensajes de texto y opera la UI por parches. La voz es una capa de entrada/salida alrededor de ese texto.

## Decisions

### D1. Voz en el navegador, detrás de interfaces
```ts
interface SpeechInputEngine  { supported: boolean; start(lang): void; stop(): void; onInterim; onFinal; onEnd; onError }
interface SpeechOutputEngine { supported: boolean; speak(text, lang): void; cancel(): void; onStart; onEnd }
```
Implementación actual: Web Speech API. Un proveedor futuro (STT/TTS con key) se implementa en el backend y se expone con mensajes nuevos del WebSocket, sin cambiar `VoiceService` ni el agente.

### D2. Flujo
1. Clic en el micrófono (o manos libres activo tras una respuesta) → reconocimiento en `es-BO`/`en-US` según `/lang`.
2. Texto parcial visible en el panel mientras se habla.
3. Resultado final → `AgentService.sendText()` (igual que teclado).
4. `agent.text` → si `/panels/voice/output` está activo, se lee frase por frase.
5. Al terminar de hablar, si `handsFree` está activo, se vuelve a escuchar.

### D3. Interrupción (barge-in)
Pulsar el micrófono, escribir o enviar mientras el agente habla o piensa: se cancela la síntesis y se envía `user.interrupt`.

### D4. Elección de voz
Entre `speechSynthesis.getVoices()` del idioma (`es-*` o `en-*`), se prefiere: nombre con "Natural"/"Online"/"Neural"/"Google" → variante latinoamericana (`es-BO`, `es-419`, `es-MX`, `es-AR`, `es-US`) → cualquier `es-*`.

### D5. Shadow
`panels.voice = { output: boolean, handsFree: boolean }`. Por defecto `output: true`, `handsFree: false`. El micrófono nunca se activa solo por un parche del agente: solo el usuario lo inicia (permiso del navegador y privacidad).

## Risks / Trade-offs

- **[Riesgo] Calidad de voz según el sistema** → se elige la mejor disponible; Edge ofrece voces neuronales en español.
- **[Riesgo] Firefox sin reconocimiento** → aviso y teclado.
- **[Trade-off] Audio a servicios del navegador** → se informa en la UI; alternativa futura: STT en el backend con key.

### D6. Transcripción en el servidor (reemplaza a la Web Speech API como motor principal)
- Navegador: `getUserMedia` (cancelación de eco y ruido) → `MediaRecorder` → energía RMS con piso de ruido calibrado en los primeros 300 ms; fin tras 1,5 s de silencio después de hablar, 8 s sin voz o 30 s máximo. Medidor de nivel en el panel.
- Backend: `SpeechToTextPort` + adaptador `GeminiTranscriber`. Formatos permitidos `audio/webm|ogg|mp4|mpeg|wav|aac`, máximo 2 MB, mismo límite de turnos por minuto.
- **Anti-alucinación** (verificado): con un tono puro el modelo llegó a "transcribir" términos del vocabulario del proyecto. Se exige la marca `[SIN_VOZ]` cuando no hay voz, se descartan salidas que son solo etiquetas (`<noise>`) o solo palabras del vocabulario. Resultado: 0/7 falsos positivos (tonos y ruido) y 3/3 frases reales correctas, 1,7 s de media.
