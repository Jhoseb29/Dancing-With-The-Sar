import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { DistrictProps, RadarSchedule, RainPayload, RiskAlert, signalBand } from '../../../../core/alerts/alerts.model';
import { laPazDay, laPazTime, utcDate } from '../../../../core/alerts/la-paz-time';
import { SceneStore } from '../../../../core/scene/scene.store';
import { BasinProps } from '../../../../core/alerts/basins.model';
import { DetectionSourcesComponent } from '../detection-sources/detection-sources.component';
import { FeedingBasinsComponent } from '../feeding-basins/feeding-basins.component';
import { RiskIconComponent } from '../risk-icon/risk-icon.component';

/** Horas mínimas de vigencia si el monitor aún no informó `vigente_hasta`. */
const HOLD_HOURS = 12;

/**
 * Aviso de un distrito (formato tipo boletín: número, prioridad, vigencia, cobertura, descripción)
 * con las 4 señales, qué hacer y con qué datos reales se detectó. Dumb.
 */
@Component({
  selector: 'app-district-card',
  imports: [TranslocoPipe, RiskIconComponent, DetectionSourcesComponent, FeedingBasinsComponent],
  templateUrl: './district-card.component.html',
  styleUrl: './district-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DistrictCardComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly district = input.required<DistrictProps>();
  /** Alerta completa (indicadores) para el detalle técnico plegado. */
  readonly alert = input<RiskAlert | null>(null);
  readonly rain = input<RainPayload | null>(null);
  readonly radar = input<RadarSchedule | null>(null);
  /** Cuencas torrenciales que bajan a este distrito. */
  readonly basins = input<BasinProps[]>([]);
  readonly back = output<void>();
  readonly openBasin = output<string>();
  /** Abrir el chat (Ecos) con una pregunta sobre este distrito. */
  readonly ask = output<void>();

  protected readonly band = signalBand;
  protected readonly level = computed(() => this.district().estado?.nivel ?? 'sin');
  protected readonly data = computed(() => this.district().estado?.datos ?? null);
  protected readonly number = computed(() => (this.data()?.alerta_id ?? '').slice(0, 6).toUpperCase() || '—');
  protected readonly from = computed(() => this.when(this.district().estado?.actualizado));
  protected readonly until = computed(() => {
    const e = this.district().estado;
    if (!e) return '—';
    const iso = e.vigente_hasta ?? new Date(utcDate(e.actualizado).getTime() + HOLD_HOURS * 3_600_000).toISOString();
    return this.when(iso);
  });

  protected round(v: number | null | undefined): string {
    return v === null || v === undefined ? '—' : String(Math.round(v));
  }

  private when(iso: string | null | undefined): string {
    return iso ? `${laPazDay(iso, this.lang())} ${laPazTime(iso, this.lang())}` : '—';
  }
}
