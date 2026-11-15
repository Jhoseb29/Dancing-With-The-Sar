import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { BasinProps } from '../../../../core/alerts/basins.model';
import { BASIN_TYPE_HEX } from '../../../../core/alerts/zone-colors';

/** Ficha de una cuenca: qué tipo de peligro produce y por qué, en 3 datos. Dumb. */
@Component({
  selector: 'app-basin-card',
  imports: [TranslocoPipe, RouterLink],
  templateUrl: './basin-card.component.html',
  styleUrl: './basin-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BasinCardComponent {
  readonly basin = input.required<BasinProps>();
  readonly back = output<void>();

  protected readonly color = computed(() => BASIN_TYPE_HEX[this.basin().tipo]);
  protected readonly drop = computed(() => this.basin().cota_max_m - this.basin().cota_min_m);
  /** Hectáreas de barro nuevo vistas por el radar (1 km² = 100 ha). */
  protected readonly sedimentHa = computed(() => {
    const s = this.basin().sedimento_radar;
    return s ? Math.round(s.area_km2 * 100) : null;
  });
}
