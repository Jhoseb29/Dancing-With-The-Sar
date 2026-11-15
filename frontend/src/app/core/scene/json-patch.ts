import { PATCHABLE_PATH, PatchOp, SceneState } from './scene.model';

/**
 * Aplica un subconjunto de JSON Patch (RFC 6902: replace/add/remove) sobre una
 * copia del estado. Lanza Error con el motivo si una operación no es válida.
 * TypeScript puro: no depende de Angular.
 */
export function applyOps(state: SceneState, ops: PatchOp[]): SceneState {
  const next = structuredClone(state) as unknown as Record<string, unknown>;
  for (const op of ops) {
    if (!PATCHABLE_PATH.test(op.path)) {
      throw new Error(`Ruta no permitida: ${op.path}`);
    }
    applyOne(next, op);
  }
  return next as unknown as SceneState;
}

function applyOne(root: Record<string, unknown>, op: PatchOp): void {
  const segments = op.path.slice(1).split('/');
  const key = segments.pop() as string;
  let parent: unknown = root;
  for (const segment of segments) {
    parent = (parent as Record<string, unknown>)[segment];
    if (parent === undefined || parent === null) {
      throw new Error(`Ruta inexistente: ${op.path}`);
    }
  }

  if (Array.isArray(parent)) {
    const index = key === '-' ? parent.length : Number(key);
    if (!Number.isInteger(index) || index < 0 || index > parent.length) {
      throw new Error(`Índice inválido en ${op.path}`);
    }
    if (op.op === 'add') {
      parent.splice(index, 0, op.value);
    } else if (op.op === 'remove') {
      if (index >= parent.length) throw new Error(`No existe ${op.path}`);
      parent.splice(index, 1);
    } else {
      if (index >= parent.length) throw new Error(`No existe ${op.path}`);
      parent[index] = op.value;
    }
    return;
  }

  const target = parent as Record<string, unknown>;
  if (op.op === 'remove') {
    throw new Error(`No se puede eliminar el campo obligatorio ${op.path}`);
  }
  if (op.op === 'replace' && !(key in target)) {
    throw new Error(`No existe ${op.path}`);
  }
  target[key] = op.value;
}

/** ¿La operación toca esta ruta o una ruta hija/padre? */
export function pathsOverlap(a: string, b: string): boolean {
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}
