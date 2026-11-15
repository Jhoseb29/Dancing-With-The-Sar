import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { TankFilter, TanksService } from '../../../../core/services/tanks.service';
import { TankRole } from '../../../../core/data-access/tanks.client';

const ROLE_COLORS: Record<TankRole, string> = {
  dual: '#38bdf8',
  drought: '#eab308',
  fire: '#fb7185',
};

/**
 * Red estratégica de tanques de cosecha de lluvia: análisis hidro-espacial (DEM, NASA POWER/IMERG,
 * NASA FIRMS) + síntesis estratégica IA/determinista para cobertura cercana de sequía e incendios.
 */
@Component({
  selector: 'app-tanks-panel',
  imports: [TranslocoPipe],
  templateUrl: './tanks-panel.component.html',
  styleUrl: './tanks-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TanksPanelComponent implements OnInit {
  protected readonly tanks = inject(TanksService);
  private readonly i18n = inject(TranslocoService);

  protected readonly roleColors = ROLE_COLORS;
  protected readonly filters: TankFilter[] = ['all', 'dual', 'drought', 'fire'];
  protected readonly focusQuery = signal('');
  protected readonly isEn = computed(() => this.i18n.getActiveLang().startsWith('en'));

  ngOnInit(): void {
    void this.tanks.load();
  }

  protected onFocusInput(event: Event): void {
    this.focusQuery.set((event.target as HTMLInputElement).value);
  }

  protected runAnalysis(event?: Event): void {
    event?.preventDefault();
    const lang = this.isEn() ? 'en' : 'es';
    const q = this.focusQuery().trim() || null;
    void this.tanks.runAnalysis(q, lang);
  }

  protected trackRoleCount(role: TankRole): number {
    const list = this.tanks.network()?.tanks ?? [];
    return list.filter((t) => t.role === role).length;
  }
}
