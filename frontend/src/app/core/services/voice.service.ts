import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import type { SpeechInputEngine, SpeechOutputEngine } from '../voice/speech-engines';
import { SceneStore } from '../scene/scene.store';

const STORAGE_KEY = 'dws.voice';

interface VoicePrefs {
  readReplies: boolean;
  privacyAcknowledged: boolean;
}

function loadPrefs(): VoicePrefs {
  try {
    return {
      readReplies: false,
      privacyAcknowledged: false,
      ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}'),
    };
  } catch {
    return { readReplies: false, privacyAcknowledged: false };
  }
}

/**
 * Voz con la Web Speech API del navegador: dictar la pregunta y (opcional) escuchar la
 * respuesta corta del harness. Preferencias por usuario en localStorage (solo comodidad).
 */
@Injectable({ providedIn: 'root' })
export class VoiceService {
  private readonly scene = inject(SceneStore);
  /** El motor se descarga (import dinámico) la primera vez que se usa la voz. */
  private engines: Promise<{ input: SpeechInputEngine; output: SpeechOutputEngine }> | null = null;
  private prefs = loadPrefs();

  readonly inputSupported = 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window;
  readonly outputSupported = 'speechSynthesis' in window;
  readonly listening = signal(false);
  readonly speaking = signal(false);
  readonly interim = signal('');
  readonly error = signal<string | null>(null);
  readonly readReplies = signal(this.prefs.readReplies);
  readonly privacyAcknowledged = signal(this.prefs.privacyAcknowledged);

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      void this.engines?.then(({ input, output }) => {
        input.stop();
        output.cancel();
      });
    });
  }

  private load(): Promise<{ input: SpeechInputEngine; output: SpeechOutputEngine }> {
    this.engines ??= import('../voice/speech-engines').then((m) => ({
      input: new m.BrowserSpeechInput(),
      output: new m.BrowserSpeechOutput(),
    }));
    return this.engines;
  }

  /** Escucha una frase; al terminar entrega el texto final a `onText`. */
  async listen(onText: (text: string) => void): Promise<void> {
    const { input } = await this.load();
    if (this.listening()) {
      input.stop();
      return;
    }
    this.interrupt();
    this.error.set(null);
    this.interim.set('');
    this.listening.set(true);
    input.start(this.scene.lang(), {
      onInterim: (text) => this.interim.set(text),
      onFinal: (text) => onText(text),
      onEnd: () => {
        this.listening.set(false);
        this.interim.set('');
      },
      onError: (code) => this.error.set(code),
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
