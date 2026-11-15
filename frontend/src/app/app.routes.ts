import { Routes } from '@angular/router';

// Todas las features son lazy: Cesium y MapLibre quedan fuera del bundle inicial.
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'orbita' },
  { path: 'orbita', loadChildren: () => import('./features/orbit-view/orbit-view.routes') },
  { path: 'cuenca', loadChildren: () => import('./features/basin-map/basin-map.routes') },
  { path: 'eventos', loadChildren: () => import('./features/event-explorer/event-explorer.routes') },
  { path: 'laboratorio', loadChildren: () => import('./features/temporal-lab/temporal-lab.routes') },
  { path: 'riesgo', loadChildren: () => import('./features/risk-dashboard/risk-dashboard.routes') },
  { path: 'explicaciones', loadChildren: () => import('./features/didactic-insights/didactic-insights.routes') },
  { path: 'procedencia', loadChildren: () => import('./features/data-provenance/data-provenance.routes') },
  { path: '**', redirectTo: 'orbita' },
];
