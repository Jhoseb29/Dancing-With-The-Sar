import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { AlertLevel, DistrictProps } from '../../../../core/alerts/alerts.model';
import { SceneStore } from '../../../../core/scene/scene.store';
import { RiskIconComponent } from '../risk-icon/risk-icon.component';

const LEVELS: AlertLevel[] = ['rojo', 'naranja', 'amarillo', 'verde'];

/** Resumen de la ciudad: titular, franja de colores y ranking de distritos. Dumb. */
@Component({
  selector: 'app-city-summary',
  imports: [TranslocoPipe, RiskIconComponent],
  templateUrl: './city-summary.component.html',
  styleUrl: './city-summary.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CitySummaryComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly districts = input.required<DistrictProps[]>();
  readonly pick = output<string>();

  /** De más a menos riesgo. */
  protected readonly ranking = computed(() =>
    [...this.districts()].sort((a, b) => (b.estado?.indice ?? -1) - (a.estado?.indice ?? -1)),
  );
  protected readonly counts = computed(() =>
    LEVELS.map((level) => ({ level, n: this.ranking().filter((d) => d.estado?.nivel === level).length })).filter((c) => c.n),
  );
  protected readonly worst = computed(() => this.counts()[0]?.level ?? 'sin');
  protected readonly updated = computed(() => {
    const iso = this.ranking()[0]?.estado?.actualizado;
    return iso ? new Date(iso).toLocaleTimeString(this.lang(), { hour: '2-digit', minute: '2-digit' }) : '—';
  });
}
