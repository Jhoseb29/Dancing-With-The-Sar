import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { BasinProps, BasinType } from '../../../../core/alerts/basins.model';
import { BASIN_TYPE_HEX } from '../../../../core/alerts/zone-colors';

const TYPES: BasinType[] = ['mazamorra', 'crecida_torrencial', 'inundacion'];

/** Leyenda por tipo (con conteo) y cuencas de la más a la menos torrencial. Dumb. */
@Component({
  selector: 'app-basin-list',
  imports: [TranslocoPipe],
  templateUrl: './basin-list.component.html',
  styleUrl: './basin-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BasinListComponent {
  readonly basins = input.required<BasinProps[]>();
  readonly pick = output<string>();

  protected readonly colors = BASIN_TYPE_HEX;
  protected readonly sorted = computed(() => [...this.basins()].sort((a, b) => b.melton - a.melton));
  protected readonly types = computed(() =>
    TYPES.map((t) => ({ t, n: this.basins().filter((b) => b.tipo === t).length })),
  );
}
