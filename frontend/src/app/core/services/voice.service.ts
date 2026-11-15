import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import type { SpeechInputEngine, SpeechOutputEngine } from '../voice/speech-engines';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { SceneStore } from '../scene/scene.store';

const STORAGE_KEY = 'dws.voice';

interface VoicePrefs {
  readReplies: boolean;
  privacyAcknowledged: boolean;
}

function loadPrefs(): VoicePrefs {
  try {
    return {
      readReplies: true,
      privacyAcknowledged: false,
      ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}'),
    };
  } catch {
    return { readReplies: true, privacyAcknowledged: false };
  }
}

/** Errores de la Web Speech API que se resuelven grabando y transcribiendo en el servidor. */
const SERVER_FALLBACK_ERRORS = new Set(['network', 'service-not-allowed', 'not-supported', 'language-not-supported']);

/**
 * Voz: dictar la pregunta y (opcional) escuchar la respuesta corta del harness.
 * Dictado con la Web Speech API del navegador; si falla (p. ej. `network` cuando el navegador no
 * alcanza el servicio de Google), pasa solo a grabar y transcribir en el servidor con Gemini.
 * Preferencias por usuario en localStorage (solo comodidad).
 */
@Injectable({ providedIn: 'root' })
export class VoiceService {
  private readonly scene = inject(SceneStore);
  private readonly transcribeUrl = `${inject(RuntimeConfigService).value.apiBaseUrl}/voice/transcribe`;
  /** true tras un fallo de red de la Web Speech API: se usa la transcripción del servidor. */
  private useServer = !('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
  /** El motor se descarga (import dinámico) la primera vez que se usa la voz. */
  private engines: Promise<{ input: SpeechInputEngine; server: SpeechInputEngine; output: SpeechOutputEngine }> | null = null;
  private prefs = loadPrefs();

  readonly inputSupported =
    'SpeechRecognition' in window ||
    'webkitSpeechRecognition' in window ||
    (typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia);
  readonly outputSupported = 'speechSynthesis' in window;
  readonly listening = signal(false);
  readonly speaking = signal(false);
  readonly interim = signal('');
  readonly error = signal<string | null>(null);
  readonly readReplies = signal(this.prefs.readReplies);
  readonly privacyAcknowledged = signal(this.prefs.privacyAcknowledged);

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      void this.engines?.then(({ input, server, output }) => {
        input.stop();
        server.stop();
        output.cancel();
      });
    });
  }

  private load(): Promise<{ input: SpeechInputEngine; server: SpeechInputEngine; output: SpeechOutputEngine }> {
    this.engines ??= import('../voice/speech-engines').then((m) => ({
      input: new m.BrowserSpeechInput(),
      server: new m.ServerSpeechInput(this.transcribeUrl),
      output: new m.BrowserSpeechOutput(),
    }));
    return this.engines;
  }

  /** Escucha una frase; al terminar entrega el texto final a `onText`. */
  async listen(onText: (text: string) => void): Promise<void> {
    const engines = await this.load();
    const input = this.useServer ? engines.server : engines.input;
    if (this.listening()) {
      input.stop();
      return;
    }
    this.interrupt();
    this.error.set(null);
    this.interim.set('');
    this.listening.set(true);
    let fallback = false;
    input.start(this.scene.lang(), {
      onInterim: (text) => this.interim.set(text),
      onFinal: (text) => onText(text),
      onEnd: () => {
        this.listening.set(false);
        this.interim.set('');
        // El navegador no alcanzó su servicio de voz: reintentar ya, grabando para el servidor.
        if (fallback) void this.listen(onText);
      },
      onError: (code) => {
        if (!this.useServer && SERVER_FALLBACK_ERRORS.has(code) && engines.server.supported) {
          this.useServer = true;
          fallback = true;
          return;
        }
        this.error.set(code);
      },
    });
  }

  async speak(text: string): Promise<void> {
    if (!this.readReplies() || !this.outputSupported || !text) return;
    const { output } = await this.load();
    output.speak(text, this.scene.lang(), {
      onStart: () => this.speaking.set(true),
      onEnd: () => this.speaking.set(false),
    });
  }

  /** Reproduce una frase de bienvenida (como la mascota Jucu) sin depender de `readReplies`. */
  async speakAnnouncement(
    text: string,
    callbacks?: { onDone?: () => void; onBlocked?: () => void },
  ): Promise<void> {
    if (!this.outputSupported || !text) {
      callbacks?.onDone?.();
      return;
    }
    const { output } = await this.load();
    output.speak(text, this.scene.lang(), {
      onStart: () => this.speaking.set(true),
      onEnd: () => {
        this.speaking.set(false);
        callbacks?.onDone?.();
      },
      onBlocked: () => {
        this.speaking.set(false);
        callbacks?.onBlocked?.();
      },
    });
  }

  interrupt(): void {
    void this.engines?.then(({ output }) => output.cancel());
    this.speaking.set(false);
  }

  setReadReplies(on: boolean): void {
    this.readReplies.set(on);
    if (!on) this.interrupt();
    this.save();
  }

  acknowledgePrivacy(): void {
    this.privacyAcknowledged.set(true);
    this.save();
  }

  private save(): void {
    this.prefs = {
      readReplies: this.readReplies(),
      privacyAcknowledged: this.privacyAcknowledged(),
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.prefs));
    } catch {
      // Almacenamiento bloqueado: la preferencia dura solo esta sesión.
    }
  }
}
