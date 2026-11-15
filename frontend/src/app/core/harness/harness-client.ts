// Cliente HTTP del harness NISAR. TypeScript puro: no importa @angular/*.
import type { HarnessEvent } from './harness.model';

export class HarnessHttpError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** Satélite: auto = NISAR y, si no cubre la zona, Sentinel-1. */
export type HarnessSensor = 'auto' | 'nisar' | 'sentinel-1';

/**
 * POST /api/harness/ask y lectura del stream NDJSON (una línea JSON por evento).
 * Se usa fetch (no EventSource) porque es POST y no debe re-ejecutarse al reconectar.
 */
export async function streamAsk(
  apiBaseUrl: string,
  text: string,
  onEvent: (event: HarnessEvent) => void,
  signal?: AbortSignal,
  sensor: HarnessSensor = 'auto',
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/harness/ask`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/x-ndjson' },
    body: JSON.stringify({ text, sensor }),
    signal,
  });
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => null);
    throw new HarnessHttpError(
      detail?.detail?.code ?? 'unknown',
      detail?.detail?.message ?? response.statusText,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let newline = buffer.indexOf('\n');
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        try {
          onEvent(JSON.parse(line) as HarnessEvent);
        } catch {
          // Línea no JSON: se ignora.
        }
      }
      newline = buffer.indexOf('\n');
    }
    if (done) {
      return;
    }
  }
}

/** URL servible de un archivo de una corrida (imágenes, GeoTIFF, KML, GeoJSON). */
export function runFileUrl(apiBaseUrl: string, runId: string, relativePath: string): string {
  const encoded = relativePath.split('/').map(encodeURIComponent).join('/');
  return `${apiBaseUrl}/harness/runs/${encodeURIComponent(runId)}/files/${encoded}`;
}
