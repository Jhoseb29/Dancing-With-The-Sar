/**
 * Respuestas del agente con los datos del sistema de alertas (assets/data/hidroglobe/*.json).
 * Funciones puras: texto de la pregunta -> qué mostrar en el mapa + qué narrar. Sin modelo.
 *
 *   "¿Qué desbordamientos hay?"         -> resumen de puntos desbordados, vuela al más crítico
 *   "¿Cómo está Puente Cajón?"           -> ficha de esa estación, vuela y abre su recuadro
 *   "La mazamorra de Taquiña de 2018"    -> escenario histórico: mancha en el mapa + relato
 *
 * Lo que no encaja (p. ej. "¿hay incendios en la Chiquitania?") sigue al harness radar.
 */
import { FloodScenario, Station } from './stations.model';

export type AgentAction = { type: 'station'; id: string } | { type: 'scenario'; key: string };

export interface AgentAnswer {
  message: string;
  action: AgentAction;
  level: 'rojo' | 'naranja' | 'amarillo' | 'verde';
}

const LEVEL = { ROJA: 'rojo', NARANJA: 'naranja', AMARILLA: 'amarillo', VERDE: 'verde' } as const;
const ALERT_WORD = { ROJA: 'roja', NARANJA: 'naranja', AMARILLA: 'amarilla', VERDE: 'verde (normal)' } as const;

/** Palabras de un nombre de estación que no identifican el lugar por sí solas. */
const GENERIC = new Set([
  'puente', 'paso', 'pasos', 'desnivel', 'torrentera', 'torrenteras', 'monte', 'central', 'laguna', 'medio',
  'cuenca', 'alta', 'baja', 'oeste', 'este', 'norte', 'sur', 'senamhi', 'aeropuerto', 'villa', 'puerto', 'queru',
]);
const OVERVIEW = /desbord|inund|crecid|riada|rebals|anega|alerta|emergencia|como esta(n)? (los )?rios|que (rios|puntos)|situacion/;
const HISTORY = /histor|escenario|pasad|antes|20\d\d|aviso\s*48|pronostico/;

/** Minúsculas y sin tildes (la voz y el teclado escriben "Cajon", "cajón", "CAJÓN"). */
export function plain(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function tokens(text: string): string[] {
  return plain(text)
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 4 && !GENERIC.has(t));
}

/** Nombre para narrar: sin códigos entre paréntesis ("Río Tamborada (D14/D15)" -> "Río Tamborada"). */
function spoken(name: string): string {
  return name.replace(/\s*\([^)]*\)/g, '').trim();
}

/** "Río Rocha" -> "el río Rocha"; "Torrentera Taquiña" -> "la torrentera Taquiña". */
function onRiver(rio: string): string {
  const [first, ...rest] = rio.split(' ');
  const article = /^r[ií]o$/i.test(first) ? 'el' : /^torrentera$/i.test(first) ? 'la' : '';
  return article ? `${article} ${first.toLowerCase()} ${rest.join(' ')}` : rio;
}

/** Lugares de Cochabamba que pueden aparecer con mayúscula en una pregunta sobre el sistema. */
const LOCAL_PLACES = new Set(['cochabamba', 'tunari', 'rocha', 'sacaba', 'quillacollo', 'cercado', 'tiquipaya', 'colcapirhua', 'vinto', 'chapare', 'bolivia']);
const ARTICLES = new Set(['la', 'el', 'los', 'las', 'de', 'del', 'en', 'hay', 'que', 'como', 'cual', 'cuales', 'donde', 'hoy']);

/** Palabras con mayúscula que no son de Cochabamba (p. ej. "La Mojana, Colombia"): la pregunta es de otro lugar. */
function mentionsOtherPlace(question: string, stations: Station[]): boolean {
  const known = new Set([
    ...LOCAL_PLACES,
    ...stations.flatMap((s) => plain(`${s.nombre} ${s.rio} ${s.zona} ${s.cuenca}`).split(/[^a-z0-9]+/)),
  ]);
  const words = question.replace(/^[¿¡\s]*\S+/, '').match(/\p{Lu}[\p{L}]+/gu) ?? [];
  return words.map(plain).some((w) => !ARTICLES.has(w) && !known.has(w));
}

function meters(value: number): string {
  return value < 1 ? `${Math.round(value * 100)} centímetros` : `${value.toFixed(2).replace(/\.?0+$/, '')} metros`;
}

function matchStation(q: string, stations: Station[]): Station | null {
  const order = ['VERDE', 'AMARILLA', 'NARANJA', 'ROJA'];
  let best: { st: Station; score: number } | null = null;
  for (const st of stations) {
    const words = new Set([...tokens(st.nombre), ...tokens(st.rio)]);
    const score = [...words].filter((w) => q.includes(w)).length;
    if (!score) continue;
    if (!best || score > best.score || (score === best.score && order.indexOf(st.alerta) > order.indexOf(best.st.alerta))) {
      best = { st, score };
    }
  }
  return best?.st ?? null;
}

function matchScenario(q: string): string | null {
  const keys: [string, RegExp][] = [
    ['taquina_2018', /taquina|mazamorra|tiquipaya|2018|2020/],
    ['albarrancho_2024', /albarrancho|maica|2024/],
    ['pasos_desnivel_2022', /pasos?( a)? desnivel|huayna|cala cala|barrientos|2022/],
    ['rocha_crecida_2026', /aviso\s*48|pronostico|2026|rocha/],
  ];
  return keys.find(([, re]) => re.test(q))?.[0] ?? null;
}

function describeStation(st: Station): string {
  const state =
    st.falta_desborde <= 0
      ? `ya se desbordó: está ${meters(Math.abs(st.falta_desborde))} por encima del umbral`
      : `le faltan ${meters(st.falta_desborde)} para desbordarse`;
  return (
    `${spoken(st.nombre)}, en ${onRiver(st.rio)}, está en alerta ${ALERT_WORD[st.alerta]}. ` +
    `El nivel es de ${meters(st.nivel_actual)} y el umbral de ${meters(st.nivel_roja)}, así que ${state}. ` +
    `Cayeron ${st.precipitacion_24h} milímetros de lluvia en 24 horas, el suelo está al ${st.humedad_suelo_pct} por ciento ` +
    `de humedad y GloFAS da ${st.glofas_prob_desborde} por ciento de probabilidad de desborde. ${st.tendencia}.`
  );
}

function overview(stations: Station[]): AgentAnswer | null {
  if (!stations.length) return null;
  const desbordadas = stations.filter((s) => s.falta_desborde <= 0).sort((a, b) => a.falta_desborde - b.falta_desborde);
  const alBorde = stations
    .filter((s) => s.falta_desborde > 0 && s.falta_desborde <= 0.2)
    .sort((a, b) => a.falta_desborde - b.falta_desborde);
  const peor = desbordadas[0] ?? alBorde[0] ?? stations.find((s) => s.alerta === 'ROJA') ?? stations[0];
  const lista = (list: Station[], max: number, f: (s: Station) => string) => {
    const items = list.slice(0, max).map(f);
    if (list.length > max) items.push(`${list.length - max} más`);
    return items.length > 1 ? `${items.slice(0, -1).join(', ')} y ${items.at(-1)}` : (items[0] ?? '');
  };
  const parts: string[] = [];
  if (desbordadas.length) {
    parts.push(
      `Hay ${desbordadas.length} puntos desbordados en Cochabamba: ` +
        lista(desbordadas, 4, (s) => `${spoken(s.nombre)} (${meters(Math.abs(s.falta_desborde))} sobre el umbral)`) +
        '.',
    );
  } else {
    parts.push('Ahora no hay puntos desbordados en Cochabamba.');
  }
  if (alBorde.length) {
    parts.push(
      `Al borde del desborde están ${lista(alBorde, 3, (s) => `${spoken(s.nombre)} (faltan ${meters(s.falta_desborde)})`)}.`,
    );
  }
  parts.push(
    `El más crítico es ${spoken(peor.nombre)}: ${peor.tendencia.charAt(0).toLowerCase()}${peor.tendencia.slice(1)}, ` +
      `con ${peor.precipitacion_24h} milímetros de lluvia en 24 horas y el suelo al ${peor.humedad_suelo_pct} por ciento. Te llevo ahí.`,
  );
  return { message: parts.join(' '), action: { type: 'station', id: peor.id }, level: LEVEL[peor.alerta] };
}

function describeScenario(key: string, sc: FloodScenario): AgentAnswer {
  const zonas = sc.features.map((f) => f.properties.zona).join('; ');
  const severity = plain(sc.severidad);
  return {
    message:
      `${sc.title}. ${sc.descripcion} Fue un evento de tipo ${sc.tipo.toLowerCase()}, severidad ${sc.severidad.toLowerCase()}. ` +
      `El satélite GPM midió ${sc.lluvia_gpm_30m} milímetros de lluvia en 30 minutos, la humedad del suelo SMAP estaba en ` +
      `${sc.smap_humedad} por ciento y el radar marcó una anomalía de ${sc.sar_backscatter_anomaly_db} decibeles. ` +
      `En el mapa te muestro la zona afectada: ${zonas}.`,
    action: { type: 'scenario', key },
    level: severity.includes('naranja') || severity.includes('alta') ? 'naranja' : 'rojo',
  };
}

/** Respuesta con los datos del sistema de alertas, o null si la pregunta no es sobre él. */
export function answerFromData(
  question: string,
  stations: Station[],
  scenarios: Record<string, FloodScenario>,
): AgentAnswer | null {
  const q = plain(question);
  if (HISTORY.test(q)) {
    const key = matchScenario(q);
    if (key && scenarios[key]) return describeScenario(key, scenarios[key]);
  }
  // Otro lugar ("¿inundaciones en La Mojana, Colombia?"): lo responde el harness radar.
  if (mentionsOtherPlace(question, stations)) return null;
  const st = matchStation(q, stations);
  if (st) {
    return { message: describeStation(st), action: { type: 'station', id: st.id }, level: LEVEL[st.alerta] };
  }
  return OVERVIEW.test(q) ? overview(stations) : null;
}
