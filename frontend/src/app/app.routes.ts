import { Routes } from '@angular/router';

// Todas las features son lazy: Cesium y MapLibre quedan fuera del bundle inicial.
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'orbita' },
  { path: 'orbita', loadChildren: () => import('./features/orbit-view/orbit-view.routes') },
  { path: 'cuenca', loadChildren: () => import('./features/basin-map/basin-map.routes') },
  { path: 'eventos', loadChildren: () => import('./features/event-explorer/event-explorer.routes') },
  { path: 'riesgo', loadChildren: () => import('./features/risk-dashboard/risk-dashboard.routes') },
  // Sin entrada en el menú: es donde el harness muestra sus resultados radar.
  { path: 'explicaciones', loadChildren: () => import('./features/didactic-insights/didactic-insights.routes') },
  { path: '**', redirectTo: 'orbita' },
];
