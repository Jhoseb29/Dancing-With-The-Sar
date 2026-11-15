import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { BasinRain } from '../../../../core/alerts/alerts.model';
import { BasinProps } from '../../../../core/alerts/basins.model';
import { laPazTime } from '../../../../core/alerts/la-paz-time';
import { BASIN_TYPE_HEX } from '../../../../core/alerts/zone-colors';
import { SceneStore } from '../../../../core/scene/scene.store';

/** Cuencas torrenciales que bajan a un distrito, con la lluvia que vio el satélite en cada una. Dumb. */
@Component({
  selector: 'app-feeding-basins',
  imports: [TranslocoPipe],
  templateUrl: './feeding-basins.component.html',
  styleUrl: './feeding-basins.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeedingBasinsComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly basins = input.required<BasinProps[]>();
  readonly rain = input<Record<string, BasinRain> | null | undefined>(null);
  readonly open = output<string>();

  protected readonly rows = computed(() =>
    this.basins()
      .map((b) => ({ b, color: BASIN_TYPE_HEX[b.tipo], r: this.rain()?.[b.id] ?? null }))
      .sort((x, y) => (y.r?.max_mm_h ?? 0) - (x.r?.max_mm_h ?? 0) || y.b.melton - x.b.melton),
  );

  protected time(iso: string | undefined): string {
    return laPazTime(iso, this.lang());
  }
}
