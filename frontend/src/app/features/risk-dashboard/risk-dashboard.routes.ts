import { Routes } from '@angular/router';

// Vista pendiente hasta que el backend publique datos reales (sin mocks).
export default [
  {
    path: '',
    loadComponent: () =>
      import('../../shared/components/pending-feature/pending-feature.component').then((m) => m.PendingFeatureComponent),
    data: {
      titleKey: 'nav.risk',
      descriptionKey: 'pending.risk',
      needs: ['risk-assessment (gateway-ts)', 'PMTiles de riesgo', 'GET /api/gamc/wms (Emergencias)'],
    },
  },
] satisfies Routes;
