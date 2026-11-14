# 06 · Sistema de Diseño ("Control de Misión")

Interfaz oscura, monocromática y técnica, inspirada en la estética de paneles de control aeroespaciales: tipografía industrial en mayúsculas espaciadas sobre negro absoluto, botones de contorno fino y **cero color decorativo**. En nuestra app, el papel que en ese estilo cumple la fotografía a pantalla completa lo cumplen **el globo, el mapa y los datos**.

> Basado en una referencia de estilo externa adaptada al proyecto. No usamos nombres, logos ni tipografías propietarias de terceros.

Especificación verificable: [`openspec/changes/06-frontend-geo-engine-and-performance/specs/frontend-design-system/spec.md`](../openspec/changes/06-frontend-geo-engine-and-performance/specs/frontend-design-system/spec.md).

---

## 1. Principios

1. **Negro absoluto como lienzo.** Toda la app vive sobre `#000000`. No hay modo claro.
2. **Un solo color de primer plano.** Texto, íconos y bordes en blanco frío `#f0f0fa`.
3. **El color pertenece a los datos.** La interfaz no tiene color de acento. Solo las capas de datos (paletas de radar definidas por el backend, niveles de riesgo) llevan color. Así, cuando algo tiene color, significa algo.
4. **Tipografía de instrumento.** Etiquetas, navegación y botones en mayúsculas con espaciado 0.09–0.10em.
5. **Sin elevación.** Ni sombras, ni brillos, ni degradados en la interfaz.
6. **Contornos, nunca rellenos.** Los botones son de borde fino de 1 px.

---

## 2. Tokens

### 2.1 Colores de interfaz

| Token | Valor | Uso |
| :--- | :--- | :--- |
| `--color-void-black` | `#000000` | Fondo de toda la app. |
| `--color-star-white` | `#f0f0fa` | Texto, íconos, bordes principales, botones. |
| `--color-muted-text` | `#9a9aa3` | **Adaptación:** texto secundario legible (contraste ≈ 7:1 sobre negro). |
| `--color-dim-steel` | `#545457` | Bordes secundarios, separadores, estados deshabilitados. **No** para texto que deba leerse (contraste insuficiente). |
| `--color-dark-gunmetal` | `#404040` | Separadores de muy bajo énfasis. |
| `--color-overlay` | `rgba(0, 0, 0, 0.72)` | **Adaptación:** fondo de paneles flotantes sobre el mapa para garantizar legibilidad. |

### 2.2 Colores de datos (no son de la interfaz)

* **Capas SAR, DEM y desplazamiento:** su paleta viene del bloque `display` del catálogo (definido por el backend). El frontend nunca la inventa.
* **Niveles de riesgo:** paleta definida junto al contrato de `risk-assessment`.
* Las paletas de datos deben ser perceptualmente uniformes y aptas para daltonismo.

### 2.3 Tipografía

| Token | Valor |
| :--- | :--- |
| `--font-primary` | `'Barlow', ui-sans-serif, system-ui, sans-serif` (autohospedada con `@fontsource/barlow`, licencia OFL) |
| Pesos | 400 (texto) · 700 (etiquetas, botones, titulares) |
| Números | `font-feature-settings: "tnum" on;` para cifras alineadas (coordenadas, dB, mm, cuenta regresiva) |

| Rol | Tamaño | Interlineado | Espaciado | Estilo |
| :--- | :--- | :--- | :--- | :--- |
| Titular de sección | 48 px (32 px en móvil) | 1.0–1.25 | 0.02em | 700, MAYÚSCULAS |
| Texto de cuerpo | 13 px | 1.7 | 0.10em | 400 |
| Texto de cuerpo grande | 16 px | 1.5 | 0.10em | 400 |
| Etiquetas, navegación, botones | 12 px | 1.5 | 0.10em | 700, MAYÚSCULAS |
| Leyendas y notas | 10 px | 1.5 | 0.09em | 400, MAYÚSCULAS (**solo** textos no esenciales) |

**Adaptación de accesibilidad:** cualquier texto necesario para entender un dato (valores, advertencias, madurez) usa mínimo 12 px.

### 2.4 Espaciado, radios y layout

* Escala: `4, 10, 12, 13, 15, 18, 20, 24, 30, 40, 60` px (`--spacing-*`).
* Separación entre elementos: 18 px · entre secciones: 60 px · relleno de paneles: 20 px.
* Radios: 4 px para todo lo estructural; 32 px solo para toggles tipo píldora.

---

## 3. Componentes base (`shared/components/`)

| Componente | Descripción |
| :--- | :--- |
| **Botón fantasma** | Borde 1 px `#f0f0fa`, fondo transparente, radio 4 px, texto 12 px 700 MAYÚSCULAS 0.10em, relleno 12×20 px. Hover: fondo blanco al 8 %. |
| **Botón secundario** | Igual, con borde y texto `#545457`→`#9a9aa3`. |
| **Toggle píldora** | Radio 32 px; para selectores compactos (polarización HH/HV, idioma ES/EN, capas). |
| **Barra superior** | Transparente sobre el globo o mapa, sin sombra ni blur. Nombre del proyecto a la izquierda, navegación a la derecha y, en el extremo derecho, el widget **`pass-countdown`** (próximo paso de NISAR) con borde de 1 px, como el selector de lanzamientos de la referencia. |
| **Panel flotante** | Bloque en el tercio izquierdo (máx. 450 px), fondo `--color-overlay`, borde 1 px `#404040`, radio 4 px. Contiene títulos, controles y leyendas sobre el mapa. |
| **Badge de madurez** | Monocromático, distinguido por el **trazo** del borde: `VALIDATED` sólido, `PROVISIONAL` discontinuo, `BETA` punteado. Siempre con el texto, nunca solo el estilo. |
| **Leyenda de capa** | Barra de color generada desde `display.colormap` + unidades; es el único lugar de la interfaz con color. |

---

## 4. Layout por vista

* **`orbit-view`:** el globo ocupa el 100 % de la pantalla; titular y texto flotan en el tercio izquierdo; la cuenta regresiva vive en la barra superior.
* **`basin-map`, `temporal-lab`, `risk-dashboard`:** el mapa ocupa el 100 %; los controles van en paneles flotantes a la izquierda; la gráfica de series aparece como panel inferior colapsable.
* **Móvil (≥ 360 px):** los paneles pasan a una hoja inferior deslizable; titulares a 32 px.

---

## 5. Lo que adaptamos de la referencia y por qué

| Regla original | Adaptación | Motivo |
| :--- | :--- | :--- |
| Ningún color de acento | Color solo en las capas de datos y su leyenda | Una app de datos científicos necesita paletas para leer valores. |
| Texto sin paneles ni fondos | Paneles con fondo negro al 72 % y borde fino | Sobre un mapa con capas el texto puede quedar ilegible. |
| Texto secundario en `#545457` | Texto secundario en `#9a9aa3` | `#545457` no cumple contraste mínimo WCAG sobre negro. |
| Texto de 10 px | 10 px solo para notas no esenciales; datos ≥ 12 px | Accesibilidad. |
| Una sola columna sin barra lateral | Paneles flotantes en el tercio izquierdo | El mapa es la "imagen" a pantalla completa; los controles flotan sobre ella. |
| Tipografía D-DIN | Barlow (alternativa libre recomendada por la propia referencia) | Licencia abierta y autohospedable. |

---

## 6. Tokens CSS (`frontend/src/styles/_tokens.scss`)

```scss
:root {
  --color-void-black: #000000;
  --color-star-white: #f0f0fa;
  --color-muted-text: #9a9aa3;
  --color-dim-steel: #545457;
  --color-dark-gunmetal: #404040;
  --color-overlay: rgba(0, 0, 0, 0.72);

  --font-primary: 'Barlow', ui-sans-serif, system-ui, sans-serif;
  --font-weight-regular: 400;
  --font-weight-bold: 700;

  --text-caption: 10px;
  --text-label: 12px;
  --text-body: 13px;
  --text-body-lg: 16px;
  --text-headline: 48px;
  --tracking-label: 0.10em;
  --tracking-caption: 0.09em;
  --tracking-headline: 0.02em;

  --spacing-4: 4px;   --spacing-10: 10px; --spacing-12: 12px; --spacing-13: 13px;
  --spacing-15: 15px; --spacing-18: 18px; --spacing-20: 20px; --spacing-24: 24px;
  --spacing-30: 30px; --spacing-40: 40px; --spacing-60: 60px;

  --section-gap: 60px;
  --panel-padding: 20px;
  --element-gap: 18px;

  --radius-md: 4px;
  --radius-pill: 32px;
}
```
