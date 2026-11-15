import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { DistrictProps, RadarSchedule, RainPayload } from '../../../../core/alerts/alerts.model';
import { laPazDay, laPazTime, utcDate } from '../../../../core/alerts/la-paz-time';
import { SceneStore } from '../../../../core/scene/scene.store';
import { RiskIconComponent } from '../risk-icon/risk-icon.component';

interface Clue {
  icon: string;
  key: string;
  params: Record<string, string | number>;
  href: string;
}

const LINKS = {
  imerg: 'https://gpm.nasa.gov/data/imerg',
  dem: 'https://registry.opendata.aws/copernicus-dem/',
  radar: 'https://search.asf.alaska.edu/',
};

/**
 * "¿Con qué lo detectamos?": cada pista con su dato real y su fuente. Con `district` usa los
 * valores de ese distrito; sin él, los de la ciudad. Incluye cuándo el radar podrá verificar. Dumb.
 */
@Component({
  selector: 'app-detection-sources',
  imports: [TranslocoPipe, RiskIconComponent],
  templateUrl: './detection-sources.component.html',
  styleUrl: './detection-sources.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DetectionSourcesComponent {
  private readonly lang = inject(SceneStore).lang;
  readonly rain = input<RainPayload | null>(null);
  readonly radar = input<RadarSchedule | null>(null);
  readonly district = input<DistrictProps | null>(null);

  /** Radar: ¿ya pasó después de la tormenta? Si no, la próxima pasada estimada. */
  protected readonly verify = computed(() => {
    const r = this.radar();
    const stormIso = this.district()?.estado?.datos?.rafaga?.cuando ?? this.rain()?.pico.cuando ?? null;
    const storm = stormIso ? utcDate(stormIso).toISOString().slice(0, 10) : null;
    const missions = (['NISAR', 'Sentinel-1'] as const)
      .map((m) => ({ m, ...r?.[m] }))
      .filter((x) => x.ultima || x.proxima_estimada);
    const after = missions.find((x) => storm && x.ultima && x.ultima > storm);
    if (after) return { key: 'risk.src.radarDone', params: { m: after.m, d: laPazDay(after.ultima, this.lang()) } };
    const next = missions
      .filter((x) => x.proxima_estimada)
      .sort((a, b) => (a.proxima_estimada! < b.proxima_estimada! ? -1 : 1))[0];
    return next
      ? { key: 'risk.src.radarNext', params: { m: next.m, d: laPazDay(next.proxima_estimada, this.lang()) } }
      : { key: 'risk.src.radarUnknown', params: {} };
  });

  protected readonly lastPasses = computed(() =>
    (['NISAR', 'Sentinel-1'] as const)
      .map((m) => ({ m, d: this.radar()?.[m]?.ultima ?? null }))
      .filter((x) => x.d)
      .map((x) => `${x.m} ${laPazDay(x.d, this.lang())}`)
      .join(' · '),
  );

  protected readonly clues = computed<Clue[]>(() => {
    const d = this.district()?.estado?.datos;
    const rain = this.rain();
    const burst = d?.rafaga ?? (rain?.pico.cuando ? { max_mm_h: rain.pico.max_30min_mm_h, cuando: rain.pico.cuando } : null);
    const lang = this.lang();
    const out: Clue[] = [];
    out.push(
      burst?.cuando
        ? {
            icon: 'lluvia',
            key: 'risk.src.rain',
            params: { mm: Math.round((burst.max_mm_h ?? 0) * 10) / 10, t: laPazTime(burst.cuando, lang), d: laPazDay(burst.cuando, lang) },
            href: LINKS.imerg,
          }
        : { icon: 'lluvia', key: 'risk.src.rainNone', params: {}, href: LINKS.imerg },
    );
    if (d?.valores.lluvia_antecedente_mm !== null && d?.valores.lluvia_antecedente_mm !== undefined) {
      out.push({
        icon: 'suelo',
        key: 'risk.src.soil',
        params: { mm: Math.round(d.valores.lluvia_antecedente_mm) },
        href: LINKS.imerg,
      });
    } else {
      out.push({ icon: 'suelo', key: 'risk.src.soilCity', params: {}, href: LINKS.imerg });
    }
    out.push(
      d?.valores.ladera_fuerte_pct !== null && d?.valores.ladera_fuerte_pct !== undefined
        ? {
            icon: 'terreno',
            key: 'risk.src.terrain',
            params: { pct: Math.round(d.valores.ladera_fuerte_pct), deg: Math.round(d.valores.pendiente_media_grados ?? 0) },
            href: LINKS.dem,
          }
        : { icon: 'terreno', key: 'risk.src.terrainCity', params: {}, href: LINKS.dem },
    );
    return out;
  });
}
