## 1. Contratos

- [x] 1.1 `scene-state`/`scene-patch` schema: `panels.voice.{output,handsFree}`

## 2. Frontend

- [x] 2.1 `core/voice/speech-engines.ts`: motores de entrada y salida (Web Speech API) detrás de interfaces
- [x] 2.2 `core/services/voice.service.ts` (Signals, barge-in, manos libres)
- [x] 2.3 `agent-dock`: micrófono, texto parcial, interruptores, avisos de privacidad y soporte
- [x] 2.4 i18n es/en

## 3. Backend

- [x] 3.1 Prompt: texto apto para leerse en voz alta

## 4. Verificación

- [x] 4.1 Síntesis: saludo leído en 3 frases con "Microsoft Raul - Spanish (Mexico)" (mejor de 2 voces es); "¿" conservado
- [x] 4.2 Reconocimiento con micrófono real: confirmado por el usuario con la transcripción en el servidor (sección 5)
- [x] 4.3a Barge-in con "Callar": la voz se detiene al instante
- [x] 4.3b Manos libres con micrófono simulado (2026-11-14): 1 clic → voz → agente actúa → lee la respuesta → el micrófono se reabre solo (2.ª ronda OK) → con silencio se cierra a los 8 s sin enviar nada. La voz empieza 1,2 s después de `agent.text`. Pendiente solo la prueba con el micrófono real del usuario (5.6).
- [x] 4.4 Build sin warnings

## 5. Transcripción en el servidor (tras fallo `network` del navegador del usuario)

- [x] 5.1 `SpeechToTextPort` + `GeminiTranscriber` con vocabulario y anti-alucinación
- [x] 5.2 Mensajes `user.audio` / `user.transcript`, estado `transcribing`, errores `no_speech`/`stt_error`/`audio_too_large` (schema actualizado)
- [x] 5.3 `RecorderAudioCapture`: grabación Opus, detección de silencio, medidor de nivel
- [x] 5.4 Prueba de punta a punta por WebSocket con un clip real: transcripción en 2,6 s y el agente actuó (cuenca + emergencias + Cochabamba)
- [x] 5.5 Prueba en navegador con micrófono simulado: grabación → corte por silencio → 46 KB enviados; un tono da "No se entendió" sin enviar nada al agente
- [x] 5.6 Prueba con el micrófono real del usuario: funciona (2026-11-14)
