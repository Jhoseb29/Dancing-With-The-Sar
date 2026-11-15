/** Fechas de los datos (UTC) mostradas en hora de Bolivia. */
const TZ = 'America/La_Paz';

/** '2026-11-15T05:00' (UTC, sin zona) o ISO completo → Date. */
export function utcDate(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function laPazTime(iso: string | null | undefined, lang: string): string {
  return iso ? utcDate(iso).toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit', timeZone: TZ }) : '—';
}

export function laPazDay(iso: string | null | undefined, lang: string): string {
  return iso
    ? utcDate(iso.length === 10 ? `${iso}T12:00` : iso).toLocaleDateString(lang, {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
        timeZone: TZ,
      })
    : '—';
}
