/** Contrato CatalogLayer (design D9), versión mínima usada por ahora. */
export interface CatalogLayer {
  id: string;
  product: 'GCOV' | 'GUNW' | 'DEM' | 'PMTILES' | 'TABLE';
  format: 'cog' | 'pmtiles' | 'parquet' | 'csv';
  url: string;
  maturity?: 'BETA' | 'PROVISIONAL' | 'VALIDATED';
  acquisition_date?: string;
  polarization?: string;
}

/** `GET {api}/catalog/layers`. Lanza error si el backend aún no responde. */
export async function fetchCatalogLayers(apiBaseUrl: string): Promise<CatalogLayer[]> {
  const response = await fetch(`${apiBaseUrl}/catalog/layers`, { headers: { Accept: 'application/json' } });
  const contentType = response.headers.get('content-type') ?? '';
  if (!response.ok || !contentType.includes('application/json')) {
    throw new Error(`catalog/layers no disponible (${response.status})`);
  }
  return (await response.json()) as CatalogLayer[];
}
