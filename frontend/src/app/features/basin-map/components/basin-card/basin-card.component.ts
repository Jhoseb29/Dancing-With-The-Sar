import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { BasinRain, RadarSchedule } from '../../../../core/alerts/alerts.model';
import { BasinProps } from '../../../../core/alerts/basins.model';
import { BASIN_TYPE_HEX } from '../../../../core/alerts/zone-colors';
import { SatelliteSawComponent } from '../../../../shared/components/satellite-saw/satellite-saw.component';

/** Ficha de una cuenca: qué tipo de peligro produce y por qué, en 3 datos. Dumb. */
@Component({
  selector: 'app-basin-card',
  imports: [TranslocoPipe, RouterLink, SatelliteSawComponent],
  templateUrl: './basin-card.component.html',
  styleUrl: './basin-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BasinCardComponent {
  readonly basin = input.required<BasinProps>();
  /** Lluvia IMERG de las últimas 24 h sobre esta cuenca. */
  readonly rain = input<BasinRain | null>(null);
  readonly radar = input<RadarSchedule | null>(null);
  readonly back = output<void>();

  protected readonly color = computed(() => BASIN_TYPE_HEX[this.basin().tipo]);
  protected readonly drop = computed(() => this.basin().cota_max_m - this.basin().cota_min_m);
  /** Hectáreas de barro nuevo vistas por el radar (1 km² = 100 ha). */
  protected readonly sedimentHa = computed(() => {
    const s = this.basin().sedimento_radar;
    return s ? Math.round(s.area_km2 * 100) : null;
  });
}
