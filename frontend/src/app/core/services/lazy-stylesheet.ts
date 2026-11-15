/** Inserta una hoja de estilos una sola vez (para CSS de motores cargados de forma diferida). */
export function ensureStylesheet(path: string): void {
  const href = new URL(path, document.baseURI).href;
  if (document.querySelector(`link[href="${href}"]`)) {
    return;
  }
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  document.head.appendChild(link);
}
