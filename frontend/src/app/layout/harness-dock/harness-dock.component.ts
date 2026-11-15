import {
  ChangeDetectionStrategy,
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
import { MarkdownPipe } from '../../shared/pipes/markdown.pipe';

const EXAMPLES = [
  'harness.examples.fires',
  'harness.examples.basin',
  'harness.examples.flood',
] as const;

/** Chat con el harness NISAR: pregunta en texto → progreso en vivo → respuesta, lección y mapas. */
@Component({
  selector: 'app-harness-dock',
  imports: [TranslocoPipe, MarkdownPipe],
  templateUrl: './harness-dock.component.html',
  styleUrl: './harness-dock.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HarnessDockComponent {
  protected readonly harness = inject(HarnessService);
  private readonly i18n = inject(TranslocoService);
  protected readonly examples = EXAMPLES;
  protected readonly open = signal(false);
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
      setTimeout(() => this.input()?.nativeElement.focus(), 0);
    }
  }

  protected send(text = this.draft()): void {
    if (this.harness.busy() || !text.trim()) {
      return;
    }
    void this.harness.ask(text);
    this.draft.set('');
    const el = this.input()?.nativeElement;
    if (el) el.value = '';
  }

  protected sendExample(key: string): void {
    this.send(this.i18n.translate(key));
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
