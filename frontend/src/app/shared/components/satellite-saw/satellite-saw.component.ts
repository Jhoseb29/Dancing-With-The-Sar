import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { BasinRain, RadarSchedule } from '../../../core/alerts/alerts.model';
import { laPazDay, laPazTime, utcDate } from '../../../core/alerts/la-paz-time';
import { SceneStore } from '../../../core/scene/scene.store';

/**
 * "Lo que vio el satélite": lluvia IMERG de las últimas 24 h sobre un área (barras por media hora,
 * ráfaga y total) y si el radar ya pudo mirar después de la tormenta. Dumb.
 */
@Component({
  selector: 'app-satellite-saw',
  imports: [TranslocoPipe],
  templateUrl: './satellite-saw.component.html',
  styleUrl: './satellite-saw.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SatelliteSawComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly rain = input<BasinRain | null>(null);
  readonly radar = input<RadarSchedule | null>(null);

  protected readonly bars = computed(() => {
    const serie = this.rain()?.serie_mm_h ?? [];
    const top = Math.max(1, ...serie);
    return serie.map((v, i) => ({ i, v, pct: (100 * v) / top }));
  });
  protected readonly when = computed(() => {
    const c = this.rain()?.cuando;
    return { t: laPazTime(c, this.lang()), d: laPazDay(c, this.lang()) };
  });
  /** ¿Ya pasó algún radar después de la ráfaga? Si no, la próxima pasada estimada. */
  protected readonly radarLine = computed(() => {
    const storm = this.rain()?.cuando ? utcDate(this.rain()!.cuando).toISOString().slice(0, 10) : null;
    const r = this.radar();
    const missions = (['NISAR', 'Sentinel-1'] as const).map((m) => ({ m, ...r?.[m] }));
    const done = missions.find((x) => storm && x.ultima && x.ultima > storm);
    if (done) return { key: 'satSaw.radarDone', params: { m: done.m, d: laPazDay(done.ultima, this.lang()) } };
    const next = missions
      .filter((x) => x.proxima_estimada)
      .sort((a, b) => (a.proxima_estimada! < b.proxima_estimada! ? -1 : 1))[0];
    return next
      ? { key: 'satSaw.radarNext', params: { m: next.m, d: laPazDay(next.proxima_estimada, this.lang()) } }
      : null;
  });
}
