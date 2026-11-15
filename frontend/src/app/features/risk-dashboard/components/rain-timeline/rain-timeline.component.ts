import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { RainPayload } from '../../../../core/alerts/alerts.model';
import { laPazDay, laPazTime } from '../../../../core/alerts/la-paz-time';
import { SceneStore } from '../../../../core/scene/scene.store';
import { RiskIconComponent } from '../risk-icon/risk-icon.component';

/** Lluvia de las últimas 24 h, media hora a media hora (barras + reproducir). Dumb. */
@Component({
  selector: 'app-rain-timeline',
  imports: [TranslocoPipe, RiskIconComponent],
  templateUrl: './rain-timeline.component.html',
  styleUrl: './rain-timeline.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RainTimelineComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly rain = input.required<RainPayload>();
  /** Media hora mostrada en el mapa; null = acumulado 24 h. */
  readonly frame = input<number | null>(null);
  readonly playing = input(false);
  readonly visible = input(true);
  readonly pick = output<number | null>();
  readonly play = output<void>();
  readonly stop = output<void>();
  readonly toggle = output<boolean>();

  /** Lluvia más fuerte de cada media hora sobre toda la zona (mm/h). */
  protected readonly bars = computed(() => {
    const slots = this.rain().slots;
    const peaks = slots.map((s) => Math.max(0, ...s.mm_h.flat().map((v) => v ?? 0)));
    const top = Math.max(1, ...peaks);
    return slots.map((s, i) => ({ i, mm: Math.round(peaks[i] * 10) / 10, pct: (100 * peaks[i]) / top, time: s.inicio }));
  });
  protected readonly total = computed(() => {
    const cells = this.rain().acumulado_mm.flat();
    return cells.length ? Math.round(Math.max(...cells)) : 0;
  });
  protected readonly current = computed(() => {
    const f = this.frame();
    return f === null ? null : (this.bars()[f] ?? null);
  });
  protected readonly preliminary = computed(() => this.rain().productos.some((p) => p.endsWith('HHE')));

  protected time(iso: string | null | undefined): string {
    return laPazTime(iso, this.lang());
  }

  protected day(iso: string | null | undefined): string {
    return laPazDay(iso, this.lang());
  }
}
