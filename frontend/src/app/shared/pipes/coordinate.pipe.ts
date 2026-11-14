import { Pipe, PipeTransform } from '@angular/core';

/** Formatea grados decimales como 17.3920° S / 66.1570° O (o W en inglés). */
@Pipe({ name: 'coordinate' })
export class CoordinatePipe implements PipeTransform {
  transform(value: number | null | undefined, axis: 'lat' | 'lon', lang = 'es'): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return '—';
    }
    const west = lang === 'es' ? 'O' : 'W';
    const hemisphere = axis === 'lat' ? (value >= 0 ? 'N' : 'S') : value >= 0 ? 'E' : west;
    return `${Math.abs(value).toFixed(4)}° ${hemisphere}`;
  }
}
