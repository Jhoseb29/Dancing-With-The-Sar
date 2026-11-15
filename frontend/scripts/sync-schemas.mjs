// Copia los JSON Schema compartidos (backend/shared/schemas, fuente única) a
// src/assets/schemas para que el frontend los cargue en runtime. Se ejecuta
// antes de `start` y `build`. La carpeta destino está ignorada por git.
import { copyFileSync, mkdirSync, readdirSync } from 'node:fs';

const source = new URL('../../backend/shared/schemas/', import.meta.url);
const target = new URL('../src/assets/schemas/', import.meta.url);
mkdirSync(target, { recursive: true });
const files = readdirSync(source).filter((f) => f.endsWith('.schema.json'));
for (const file of files) {
  copyFileSync(new URL(file, source), new URL(file, target));
}
console.log(`[sync-schemas] ${files.length} schemas copiados`);
