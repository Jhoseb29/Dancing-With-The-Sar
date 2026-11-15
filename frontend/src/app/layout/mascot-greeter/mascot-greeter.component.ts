import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { SceneStore } from '../../core/scene/scene.store';
import { VoiceService } from '../../core/services/voice.service';

export type MascotPhase = 'greeting' | 'gliding' | 'docked';

/** Duración del vuelo hacia la esquina inferior derecha (ms). */
const GLIDE_DURATION_MS = 900;
/** Cadencia de apertura/cierre de boca al hablar (ms). */
const LIP_SYNC_INTERVAL_MS = 150;
/** Velocidad del efecto máquina de escribir para la frase de bienvenida (ms/carácter). */
const TYPEWRITER_CHAR_MS = 50;

/**
 * Mascota animada "Jucu" (Jucumari / Oso Andino de anteojos del Parque Tunari con antena SAR).
 * Al iniciar la aplicación saluda bailando en el centro ("¡Bienvenido a Dancing with the SARs!")
 * reproduciendo su voz neural (`welcome-es.mp3` / `welcome-en.mp3`) y, al terminar la frase,
 * vuela suavemente hasta estacionarse en la parte inferior derecha.
 */
@Component({
  selector: 'app-mascot-greeter',
  imports: [TranslocoPipe],
  templateUrl: './mascot-greeter.component.html',
  styleUrl: './mascot-greeter.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MascotGreeterComponent implements OnInit {
  protected readonly scene = inject(SceneStore);
  protected readonly voice = inject(VoiceService);
  private readonly i18n = inject(TranslocoService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly phase = signal<MascotPhase>('greeting');
  protected readonly mouthOpen = signal(false);
  protected readonly typedText = signal('');
  protected readonly typingDone = signal(false);
  protected readonly hovered = signal(false);
  protected readonly audioPlaying = signal(false);
  protected readonly waitingForUnlock = signal(false);

  protected readonly isSpeaking = computed(
    () =>
      this.phase() === 'greeting' &&
      (!this.typingDone() || this.audioPlaying() || this.voice.speaking()),
  );

  private audio: HTMLAudioElement | null = null;
  private lipSyncTimer: ReturnType<typeof setInterval> | null = null;
  private typeTimer: ReturnType<typeof setInterval> | null = null;
  private phaseTimer: ReturnType<typeof setTimeout> | null = null;
  private glideTimer: ReturnType<typeof setTimeout> | null = null;
  private unlockCleanup: (() => void) | null = null;

  constructor() {
    // Si el usuario cambia de idioma mientras Jucu está saludando, actualizar frase y voz.
    effect(() => {
      this.scene.lang();
      untracked(() => {
        if (this.phase() === 'greeting') {
          this.startGreetingSequence();
        }
      });
    });

    this.destroyRef.onDestroy(() => {
      this.clearTimers();
      this.stopAudio();
      this.removeUnlockListener();
    });
  }

  ngOnInit(): void {
    this.startGreetingSequence();
  }

  /** Inicia la coreografía: baile en el centro + voz "¡Bienvenido a Dancing with the SARs!" + vuelo a la esquina. */
  protected startGreetingSequence(): void {
    this.clearTimers();
    this.stopAudio();
    this.removeUnlockListener();

    this.phase.set('greeting');
    this.typedText.set('');
    this.typingDone.set(false);
    this.waitingForUnlock.set(false);
    this.mouthOpen.set(true);

    const fullGreeting = this.greetingPhrase();
    let charIndex = 0;

    // 1. Máquina de escribir para la frase principal.
    this.typeTimer = setInterval(() => {
      charIndex++;
      this.typedText.set(fullGreeting.slice(0, charIndex));
      if (charIndex >= fullGreeting.length) {
        if (this.typeTimer) {
          clearInterval(this.typeTimer);
          this.typeTimer = null;
        }
        this.typingDone.set(true);
      }
    }, TYPEWRITER_CHAR_MS);

    // 2. Lip-sync inicial mientras escribe y habla.
    this.startLipSync(2600);

    // 3. Reproducir el audio neural de bienvenida (sincronizado con el vuelo final).
    this.playWelcomeAudio(true);
  }

  /** Envía a Jucu en vuelo suave hacia la esquina inferior derecha. */
  protected glideToCorner(event?: Event): void {
    event?.stopPropagation();
    if (this.phase() === 'docked' || this.phase() === 'gliding') {
      return;
    }
    this.clearTimers();
    this.stopAudio();
    this.removeUnlockListener();
    this.waitingForUnlock.set(false);
    this.mouthOpen.set(false);
    this.typingDone.set(true);
    this.typedText.set(this.greetingPhrase());
    this.phase.set('gliding');

    this.glideTimer = setTimeout(() => {
      this.phase.set('docked');
    }, GLIDE_DURATION_MS);
  }

  /** Reproduce la voz de bienvenida inmediatamente (clic en el botón de voz). */
  protected speakNow(event: Event): void {
    event.stopPropagation();
    this.removeUnlockListener();
    this.waitingForUnlock.set(false);
    if (this.audioPlaying() && this.audio && this.audio.currentTime < 0.6) {
      return;
    }
    this.playWelcomeAudio(this.phase() === 'greeting');
  }

  /** Al hacer clic en Jucu cuando está en la esquina inferior derecha, vuelve al centro a bailar y saludar. */
  protected onMascotClick(event: Event): void {
    event.stopPropagation();
    this.removeUnlockListener();
    if (this.phase() === 'docked') {
      this.startGreetingSequence();
    } else if (this.phase() === 'greeting') {
      if (this.audioPlaying() && this.audio && this.audio.currentTime < 0.6) {
        return;
      }
      this.playWelcomeAudio(true);
    }
  }

  /**
   * Reproduce el archivo MP3 neural (`welcome-es.mp3` / `welcome-en.mp3`) de forma síncrona.
   * - Si el navegador permite autoplay, suena de inmediato al abrir o refrescar la página y,
   *   al terminar el audio (`ended`), Jucu vuela a la esquina inferior derecha.
   * - Si el navegador bloquea el autoplay por ser una pestaña recién abierta sin interacción,
   *   Jucu permanece en el centro esperando el primer clic/toque/tecla en cualquier parte de la
   *   pantalla para sonar de forma síncrona y luego volar a la esquina.
   */
  private playWelcomeAudio(glideWhenFinished: boolean): void {
    this.stopAudio();
    if (this.phaseTimer) {
      clearTimeout(this.phaseTimer);
      this.phaseTimer = null;
    }

    const src =
      this.scene.lang() === 'en'
        ? 'assets/mascot/welcome-en.mp3'
        : 'assets/mascot/welcome-es.mp3';

    const audio = new Audio(src);
    audio.preload = 'auto';
    audio.volume = 1;
    this.audio = audio;

    const onFinished = () => {
      if (this.audio !== audio) return;
      this.audioPlaying.set(false);
      this.mouthOpen.set(false);
      if (glideWhenFinished && this.phase() === 'greeting') {
        if (this.phaseTimer) clearTimeout(this.phaseTimer);
        this.phaseTimer = setTimeout(() => this.glideToCorner(), 650);
      }
    };

    audio.addEventListener('ended', onFinished, { once: true });
    audio.addEventListener(
      'error',
      () => {
        if (this.audio !== audio) return;
        this.audioPlaying.set(false);
        void this.voice.speakAnnouncement(this.greetingPhrase(), {
          onDone: onFinished,
          onBlocked: () => this.armGestureUnlock(audio, glideWhenFinished),
        });
      },
      { once: true },
    );

    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => {
          if (this.audio !== audio) return;
          this.waitingForUnlock.set(false);
          this.audioPlaying.set(true);
          this.removeUnlockListener();
          this.startLipSync(2600);
          // Respaldo de seguridad por si `ended` tardara más de lo previsto.
          if (glideWhenFinished && this.phase() === 'greeting') {
            if (this.phaseTimer) clearTimeout(this.phaseTimer);
            this.phaseTimer = setTimeout(() => this.glideToCorner(), 4500);
          }
        })
        .catch(() => {
          if (this.audio !== audio) return;
          this.audioPlaying.set(false);
          this.armGestureUnlock(audio, glideWhenFinished);
        });
    }
  }

  /**
   * Cuando el navegador bloquea el audio al abrir una pestaña nueva sin clic previo,
   * mantenemos a Jucu en el centro y reproducimos `audio.play()` de forma 100 % síncrona
   * en el primer clic, toque o tecla del usuario en cualquier lugar de la pantalla.
   */
  private armGestureUnlock(audio: HTMLAudioElement, glideWhenFinished: boolean): void {
    this.removeUnlockListener();
    this.waitingForUnlock.set(true);

    const unlock = (ev: Event) => {
      const target = ev.target as HTMLElement | null;
      if (target?.closest('[data-mascot-skip]')) {
        this.removeUnlockListener();
        return;
      }
      this.removeUnlockListener();
      this.waitingForUnlock.set(false);
      audio.currentTime = 0;
      const p = audio.play();
      this.audioPlaying.set(true);
      this.startLipSync(2600);
      if (glideWhenFinished && this.phase() === 'greeting') {
        if (this.phaseTimer) clearTimeout(this.phaseTimer);
        this.phaseTimer = setTimeout(() => this.glideToCorner(), 4200);
      }
      p?.catch(() => {
        this.audioPlaying.set(false);
      });
    };

    window.addEventListener('pointerdown', unlock, { capture: true });
    window.addEventListener('keydown', unlock, { capture: true });
    this.unlockCleanup = () => {
      window.removeEventListener('pointerdown', unlock, { capture: true });
      window.removeEventListener('keydown', unlock, { capture: true });
    };
  }

  private stopAudio(): void {
    if (this.audio) {
      this.audio.pause();
      this.audio.src = '';
      this.audio = null;
    }
    this.audioPlaying.set(false);
  }

  private removeUnlockListener(): void {
    this.unlockCleanup?.();
    this.unlockCleanup = null;
  }

  private startLipSync(minDurationMs: number): void {
    if (this.lipSyncTimer) {
      clearInterval(this.lipSyncTimer);
    }
    this.mouthOpen.set(true);
    const startedAt = Date.now();
    this.lipSyncTimer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      if (elapsed < minDurationMs || this.audioPlaying() || this.voice.speaking()) {
        this.mouthOpen.update((open) => !open);
      } else {
        this.mouthOpen.set(false);
      }
    }, LIP_SYNC_INTERVAL_MS);
  }

  private greetingPhrase(): string {
    const translated = this.i18n.translate('mascot.greeting');
    if (translated && translated !== 'mascot.greeting') {
      return translated;
    }
    return this.scene.lang() === 'en'
      ? 'Welcome to Dancing with the SARs!'
      : '¡Bienvenido a Dancing with the SARs!';
  }

  private clearTimers(): void {
    if (this.lipSyncTimer) {
      clearInterval(this.lipSyncTimer);
      this.lipSyncTimer = null;
    }
    if (this.typeTimer) {
      clearInterval(this.typeTimer);
      this.typeTimer = null;
    }
    if (this.phaseTimer) {
      clearTimeout(this.phaseTimer);
      this.phaseTimer = null;
    }
    if (this.glideTimer) {
      clearTimeout(this.glideTimer);
      this.glideTimer = null;
    }
  }
}
