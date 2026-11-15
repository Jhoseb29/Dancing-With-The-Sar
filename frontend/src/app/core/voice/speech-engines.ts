// Motores de voz. TypeScript puro: no importa @angular/*.
// Web Speech API del navegador: reconocimiento (micrófono → texto) y síntesis (texto → voz).
// Sin backend ni keys. Otro proveedor puede implementar las mismas interfaces.

export type VoiceLang = 'es' | 'en';

export interface SpeechInputHandlers {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onEnd: () => void;
  onError: (code: string) => void;
}

export interface SpeechInputEngine {
  readonly supported: boolean;
  start(lang: VoiceLang, handlers: SpeechInputHandlers): void;
  stop(): void;
}

export interface SpeechOutputHandlers {
  onStart: () => void;
  onEnd: () => void;
}

export interface SpeechOutputEngine {
  readonly supported: boolean;
  speak(text: string, lang: VoiceLang, handlers: SpeechOutputHandlers): void;
  cancel(): void;
}

// ---- Tipos mínimos de SpeechRecognition (no están en todas las versiones de lib.dom) ----

interface RecognitionAlternative {
  transcript: string;
}
interface RecognitionResult {
  isFinal: boolean;
  0: RecognitionAlternative;
}
interface RecognitionEvent {
  resultIndex: number;
  results: { length: number; [index: number]: RecognitionResult };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

const RECOGNITION_LANG: Record<VoiceLang, string> = { es: 'es-BO', en: 'en-US' };

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export class BrowserSpeechInput implements SpeechInputEngine {
  private recognition: Recognition | null = null;

  get supported(): boolean {
    return recognitionCtor() !== null;
  }

  private session: ListeningSession | null = null;

  start(lang: VoiceLang, handlers: SpeechInputHandlers): void {
    const Ctor = recognitionCtor();
    if (!Ctor) {
      handlers.onError('not-supported');
      return;
    }
    this.session?.finish('restart', false);
    this.session = new ListeningSession(Ctor, RECOGNITION_LANG[lang], handlers, () => {
      this.session = null;
    });
  }

  /** El usuario pulsó "Detener": se envía lo que ya dijo. */
  stop(): void {
    this.session?.finish('user-stop', true);
  }
}

/** Silencio tras hablar que da por terminada la frase. */
const END_SILENCE_MS = 1800;
/** Tiempo máximo esperando a que el usuario empiece a hablar. */
const NO_SPEECH_MS = 8000;
/** Reinicios permitidos si el navegador corta antes de tiempo. */
const MAX_RESTARTS = 6;
const FALLBACK_LANG: Record<string, string> = { 'es-BO': 'es-ES', 'en-US': 'en-GB' };

/**
 * Una escucha completa. Usa reconocimiento continuo y decide el final por silencio,
 * porque en modo de frase única Chrome/Edge cortan ante la primera pausa. Si el
 * navegador termina antes de tiempo, retoma sin perder lo ya dicho.
 */
class ListeningSession {
  private recognition: Recognition | null = null;
  private committed = '';
  private current = '';
  private heard = false;
  private readonly startedAt = Date.now();
  private lastResultAt = Date.now();
  private restarts = 0;
  private finished = false;
  private readonly timer: ReturnType<typeof setInterval>;

  constructor(
    private readonly Ctor: RecognitionCtor,
    private lang: string,
    private readonly handlers: SpeechInputHandlers,
    private readonly onDone: () => void,
  ) {
    this.timer = setInterval(() => this.checkSilence(), 250);
    this.startInstance();
  }

  finish(reason: string, deliver: boolean): void {
    if (this.finished) return;
    this.finished = true;
    clearInterval(this.timer);
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition) {
      recognition.onend = null;
      recognition.onresult = null;
      recognition.onerror = null;
      try {
        recognition.stop();
      } catch {
        // Ya detenido.
      }
    }
    const text = this.text();
    console.info(
      `[voz] fin de escucha: ${reason}; reinicios=${this.restarts}; texto=${text ? `"${text}"` : '(vacío)'}`,
    );
    if (deliver && text) {
      this.handlers.onFinal(text);
    }
    this.handlers.onEnd();
    this.onDone();
  }

  private text(): string {
    return `${this.committed} ${this.current}`.replace(/\s+/g, ' ').trim();
  }

  private startInstance(): void {
    const recognition = new this.Ctor();
    recognition.lang = this.lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      // Transcripción completa de esta instancia (finales + parciales).
      let text = '';
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      this.current = text;
      this.lastResultAt = Date.now();
      if (text.trim()) this.heard = true;
      this.handlers.onInterim(this.text());
    };

    recognition.onerror = (event) => {
      const code = event.error;
      if (code === 'no-speech' || code === 'aborted') {
        return; // el temporizador o onend deciden
      }
      if (code === 'language-not-supported' && FALLBACK_LANG[this.lang]) {
        console.info(`[voz] ${this.lang} no soportado; usando ${FALLBACK_LANG[this.lang]}`);
        this.lang = FALLBACK_LANG[this.lang];
        return; // onend reinicia con el idioma alternativo
      }
      this.handlers.onError(code);
      this.finish(`error:${code}`, true);
    };

    recognition.onend = () => {
      if (this.finished) return;
      // El navegador cortó antes de que decidiéramos terminar: guardar y retomar.
      this.committed = this.text();
      this.current = '';
      if (this.restarts < MAX_RESTARTS) {
        this.restarts++;
        console.info(
          `[voz] el navegador cortó la escucha; retomando (${this.restarts}/${MAX_RESTARTS})`,
        );
        this.startInstance();
      } else {
        this.finish('browser-end', true);
      }
    };

    this.recognition = recognition;
    try {
      recognition.start();
    } catch (err) {
      this.handlers.onError('start-failed');
      this.finish(`start-failed: ${err instanceof Error ? err.message : String(err)}`, true);
    }
  }

  private checkSilence(): void {
    const now = Date.now();
    if (this.heard && now - this.lastResultAt > END_SILENCE_MS) {
      this.finish('silence', true);
    } else if (!this.heard && now - this.startedAt > NO_SPEECH_MS) {
      this.finish('no-speech', false);
    }
  }
}

/** Divide un texto en frases para leerlas una a una (más natural y cancelable). */
export function splitSentences(text: string): string[] {
  // Los signos de apertura ¿ ¡ quedan dentro de la frase; solo cortan los de cierre.
  return (text.match(/[^.!?…]+[.!?…]+["»)]?|[^.!?…]+$/g) ?? [text])
    .map((s) => s.trim())
    .filter(Boolean);
}

const PREFERRED_NAMES = /(natural|online|neural|google)/i;
const LATAM = ['es-BO', 'es-419', 'es-MX', 'es-AR', 'es-US', 'es-CO', 'es-CL', 'es-PE'];

/** Mejor voz disponible para el idioma (OpenSpec 10, D4). */
export function pickVoice(
  voices: SpeechSynthesisVoice[],
  lang: VoiceLang,
): SpeechSynthesisVoice | null {
  const candidates = voices.filter((v) => v.lang.toLowerCase().startsWith(lang));
  if (!candidates.length) return null;
  const score = (v: SpeechSynthesisVoice): number => {
    let s = 0;
    if (PREFERRED_NAMES.test(v.name)) s += 10;
    if (lang === 'es') {
      const i = LATAM.findIndex((code) => v.lang.toLowerCase() === code.toLowerCase());
      if (i >= 0) s += 5 - Math.min(i, 4) * 0.5;
    } else if (v.lang.toLowerCase() === 'en-us') {
      s += 3;
    }
    if (v.localService === false) s += 1;
    return s;
  };
  return [...candidates].sort((a, b) => score(b) - score(a))[0];
}

export class BrowserSpeechOutput implements SpeechOutputEngine {
  private token = 0;

  get supported(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
  }

  speak(text: string, lang: VoiceLang, handlers: SpeechOutputHandlers): void {
    if (!this.supported) return;
    const synth = window.speechSynthesis;
    const token = ++this.token;
    synth.cancel();
    const voice = pickVoice(synth.getVoices(), lang);
    const sentences = splitSentences(text);
    // `onstart` no se dispara en todos los navegadores (p. ej. pestañas en segundo plano):
    // se considera "hablando" desde que la lectura queda en cola.
    handlers.onStart();
    sentences.forEach((sentence, index) => {
      const utterance = new SpeechSynthesisUtterance(sentence);
      utterance.lang = voice?.lang ?? (lang === 'es' ? 'es-419' : 'en-US');
      if (voice) utterance.voice = voice;
      utterance.rate = 1.02;
      const finish = () => {
        if (index === sentences.length - 1 && token === this.token) handlers.onEnd();
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      synth.speak(utterance);
    });
  }

  cancel(): void {
    if (!this.supported) return;
    this.token++;
    window.speechSynthesis.cancel();
  }
}
