import { DestroyRef, Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { SceneStore } from '../scene/scene.store';
import {
  AudioCaptureEngine,
  BrowserSpeechInput,
  BrowserSpeechOutput,
  RecorderAudioCapture,
  SpeechInputEngine,
  SpeechOutputEngine,
  blobToBase64,
} from '../voice/speech-engines';
import { AgentService } from './agent.service';

const PRIVACY_KEY = 'dws.voice.privacyAck';

/**
 * Voz del agente (OpenSpec 10): micrófono → texto → agente; respuestas → voz.
 * Interrupción (barge-in) y manos libres. El micrófono solo se activa por acción del usuario.
 */
@Injectable({ providedIn: 'root' })
export class VoiceService {
  private readonly scene = inject(SceneStore);
  private readonly agent = inject(AgentService);
  /** Motor principal: grabar en el navegador y transcribir en el backend (Gemini). */
  private readonly capture: AudioCaptureEngine = new RecorderAudioCapture();
  /** Respaldo: reconocimiento del navegador si no se puede grabar. */
  private readonly input: SpeechInputEngine = new BrowserSpeechInput();
  private readonly output: SpeechOutputEngine = new BrowserSpeechOutput();

  readonly inputSupported = this.capture.supported || this.input.supported;
  readonly level = signal(0);
  readonly outputSupported = this.output.supported;
  readonly listening = signal(false);
  readonly speaking = signal(false);
  readonly interim = signal('');
  readonly error = signal<string | null>(null);
  readonly privacyAcknowledged = signal(readFlag());

  /** La conversación por voz la inició el usuario en esta sesión (requisito de manos libres). */
  private voiceSessionStarted = false;
  private lastSpokenId = 0;

  readonly settings = computed(() => this.scene.panels().voice);

  constructor() {
    // Leer en voz alta cada respuesta nueva del agente.
    effect(() => {
      const entries = this.agent.transcript();
      const last = entries[entries.length - 1];
      untracked(() => {
        if (!last || last.role !== 'agent' || last.id <= this.lastSpokenId) return;
        this.lastSpokenId = last.id;
        if (this.settings().output && this.outputSupported) {
          this.say(last.text);
        } else {
          this.maybeListenAgain();
        }
      });
    });

    // Cerrar el panel corta la voz y el micrófono.
    effect(() => {
      if (this.scene.panels().agentDock === 'closed') {
        untracked(() => this.stopAll());
      }
    });

    inject(DestroyRef).onDestroy(() => this.stopAll());
  }

  acknowledgePrivacy(): void {
    this.privacyAcknowledged.set(true);
    try {
      localStorage.setItem(PRIVACY_KEY, '1');
    } catch {
      // Sin almacenamiento: se volverá a mostrar el aviso.
    }
  }

  /** Botón de micrófono: escucha, o interrumpe al agente y escucha. */
  toggleListening(): void {
    if (this.listening()) {
      this.capture.stop(true);
      this.input.stop();
      return;
    }
    if (!this.inputSupported) {
      this.error.set('not-supported');
      return;
    }
    this.voiceSessionStarted = true;
    this.interrupt();
    this.listen();
  }

  /** Detiene la voz del agente y su turno en curso (barge-in). */
  interrupt(): void {
    if (this.speaking()) {
      this.output.cancel();
      this.speaking.set(false);
    }
    if (['transcribing', 'thinking', 'acting'].includes(this.agent.status())) {
      this.agent.interrupt();
    }
  }

  setOutput(enabled: boolean): void {
    if (!enabled) {
      this.output.cancel();
      this.speaking.set(false);
    }
    void this.scene.set('/panels/voice/output', enabled);
  }

  setHandsFree(enabled: boolean): void {
    void this.scene.set('/panels/voice/handsFree', enabled);
  }

  stopAll(): void {
    this.capture.stop(false);
    this.input.stop();
    this.level.set(0);
    this.output.cancel();
    this.listening.set(false);
    this.speaking.set(false);
    this.interim.set('');
  }

  private listen(): void {
    this.error.set(null);
    this.interim.set('');
    this.listening.set(true);
    if (this.capture.supported) {
      void this.capture.start({
        onLevel: (level) => this.level.set(level),
        onAudio: (audio, mime) => {
          void blobToBase64(audio).then((data) => this.agent.sendAudio(data, mime));
        },
        onEnd: () => {
          this.listening.set(false);
          this.level.set(0);
        },
        onError: (code) => {
          if (code !== 'no-speech') this.error.set(code);
        },
      });
      return;
    }
    this.input.start(this.scene.lang(), {
      onInterim: (text) => this.interim.set(text),
      onFinal: (text) => {
        this.interim.set('');
        this.agent.sendText(text);
      },
      onEnd: () => {
        this.listening.set(false);
        this.interim.set('');
      },
      onError: (code) => {
        // "no-speech" y "aborted" son normales; el resto se muestra.
        if (code !== 'no-speech' && code !== 'aborted') this.error.set(code);
        this.listening.set(false);
      },
    });
  }

  private say(text: string): void {
    this.output.speak(text, this.scene.lang(), {
      onStart: () => this.speaking.set(true),
      onEnd: () => {
        this.speaking.set(false);
        this.maybeListenAgain();
      },
    });
  }

  private maybeListenAgain(): void {
    if (this.settings().handsFree && this.voiceSessionStarted && this.inputSupported && !this.listening()) {
      this.listen();
    }
  }
}

function readFlag(): boolean {
  try {
    return localStorage.getItem(PRIVACY_KEY) === '1';
  } catch {
    return false;
  }
}
