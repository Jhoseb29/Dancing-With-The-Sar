import {
  ChangeDetectionStrategy,
  computed,
  Component,
  ElementRef,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { HarnessMedia } from '../../core/harness/harness.model';
import { HarnessService, HarnessTurn } from '../../core/services/harness.service';
import { AlertsService } from '../../core/services/alerts.service';
import { ChatAlertsBoxComponent } from './chat-alerts-box/chat-alerts-box.component';
import { VoiceService } from '../../core/services/voice.service';
import { MarkdownPipe } from '../../shared/pipes/markdown.pipe';

const EXAMPLES = [
  'harness.examples.yesterday',
  'harness.examples.fires',
  'harness.examples.basin',
  'harness.examples.flood',
] as const;
const SENSORS = ['auto', 'sentinel-1', 'nisar'] as const;

/** Chat con el harness NISAR: pregunta en texto → progreso en vivo → respuesta, lección y mapas. */
@Component({
  selector: 'app-harness-dock',
  imports: [TranslocoPipe, MarkdownPipe, ChatAlertsBoxComponent],
  templateUrl: './harness-dock.component.html',
  styleUrl: './harness-dock.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HarnessDockComponent {
  protected readonly harness = inject(HarnessService);
  protected readonly voice = inject(VoiceService);
  private readonly i18n = inject(TranslocoService);
  protected readonly askPrivacy = signal(false);
  protected readonly examples = EXAMPLES;
  protected readonly sensors = SENSORS;
  protected readonly open = this.harness.dockOpen;
  protected readonly alerts = inject(AlertsService);
  /** Apartado de alertas: resumen vigente y preguntas listas para explicarlas. */
  protected readonly alertSummary = computed(() => {
    const rows = (this.alerts.districts()?.features ?? []).map((f) => f.properties).filter((p) => p.estado);
    if (!rows.length) return null;
    const counts = (['rojo', 'naranja', 'amarillo', 'verde'] as const)
      .map((level) => ({ level, n: rows.filter((r) => r.estado?.nivel === level).length }))
      .filter((c) => c.n);
    const top = [...rows].sort((a, b) => (b.estado?.indice ?? 0) - (a.estado?.indice ?? 0))[0];
    const picked = this.alerts.selectedDistrict();
    return { counts, top, picked };
  });
  protected readonly draft = signal('');
  /** Turnos con la lección desplegada. */
  protected readonly expanded = signal<ReadonlySet<number>>(new Set());

  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private readonly input = viewChild<ElementRef<HTMLTextAreaElement>>('input');

  constructor() {
    // Mantener la conversación al final mientras llega progreso.
    effect(() => {
      this.harness.turns();
      untracked(() =>
        setTimeout(() => {
          const el = this.log()?.nativeElement;
          if (el) el.scrollTop = el.scrollHeight;
        }, 0),
      );
    });
  }

  protected toggle(): void {
    this.open.update((v) => !v);
    if (this.open()) {
      void this.alerts.refresh();
      setTimeout(() => this.input()?.nativeElement.focus(), 0);
    }
  }

  protected send(text = this.draft()): void {
    if (this.harness.busy() || !text.trim()) {
      return;
    }
    this.voice.interrupt();
    void this.harness.ask(text);
    this.draft.set('');
    const el = this.input()?.nativeElement;
    if (el) el.value = '';
  }

  /** Dictar la pregunta: al terminar de hablar se envía sola. */
  protected onMic(): void {
    if (!this.voice.privacyAcknowledged() && !this.voice.listening()) {
      this.askPrivacy.set(true);
      return;
    }
    void this.voice.listen((text) => this.send(text));
  }

  protected acceptPrivacy(): void {
    this.askPrivacy.set(false);
    this.voice.acknowledgePrivacy();
    this.onMic();
  }

  protected sendExample(key: string, params?: Record<string, unknown>): void {
    this.send(this.i18n.translate(key, params));
  }

  protected levelName(level: string | undefined): string {
    return this.i18n.translate(`risk.levels.${level ?? 'sin'}`).toLowerCase();
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    } else if (event.key === 'Escape') {
      this.toggle();
    }
  }

  protected toggleLesson(id: number): void {
    this.expanded.update((set) => {
      const next = new Set(set);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  protected images(turn: HarnessTurn): HarnessMedia[] {
    return turn.payload?.media.filter((m) => m.kind === 'image') ?? [];
  }

  protected downloads(turn: HarnessTurn): HarnessMedia[] {
    return turn.payload?.media.filter((m) => m.kind !== 'image') ?? [];
  }

  protected percent(turn: HarnessTurn): number {
    return Math.round(turn.progress * 100);
  }
}
