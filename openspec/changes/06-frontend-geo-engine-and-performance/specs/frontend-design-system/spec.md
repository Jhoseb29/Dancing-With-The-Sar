## ADDED Requirements

### Requirement: Tokens de diseño centralizados
El frontend SHALL definir los tokens de [`docs/06-design-system.md`](../../../../../docs/06-design-system.md) (colores, tipografía, espaciado, radios) como variables CSS en `frontend/src/styles/_tokens.scss`. Los `.scss` de componentes MUST usar esos tokens y MUST NOT contener valores de color, tamaño de fuente o radio escritos a mano.

#### Scenario: Revisión de estilos
- **WHEN** se buscan colores hexadecimales en los `.scss` de `features/`, `layout/` y `shared/`
- **THEN** no hay coincidencias fuera de `_tokens.scss`

### Requirement: Interfaz monocromática, color solo en datos
El fondo de la aplicación MUST ser `--color-void-black` y el primer plano de la interfaz `--color-star-white`. La interfaz MUST NOT usar colores de acento. El color SHALL aparecer únicamente en las capas de datos y en sus leyendas, tomado del `display` del catálogo o de la paleta de riesgo del backend.

#### Scenario: Botón principal
- **WHEN** se muestra la acción principal de una vista
- **THEN** es un botón de contorno de 1 px en `--color-star-white`, sin relleno

#### Scenario: Capa con color
- **WHEN** se activa una capa GCOV
- **THEN** el único color en pantalla, aparte del globo o mapa base, es el de la capa y su leyenda

### Requirement: Tipografía de instrumento
La fuente principal SHALL ser Barlow autohospedada (`@fontsource/barlow`, sin peticiones a servicios externos de fuentes). Etiquetas, navegación y botones SHALL ir en mayúsculas con espaciado `0.10em`; los titulares a 48 px (32 px en móvil) con `0.02em`. Las cifras MUST usar `font-feature-settings: "tnum"`.

#### Scenario: Valor numérico
- **WHEN** se muestra un valor en dB, mm, coordenadas o la cuenta regresiva
- **THEN** las cifras usan dígitos tabulares y no "bailan" al actualizarse

### Requirement: Sin elevación
Los componentes de interfaz MUST NOT usar `box-shadow`, `text-shadow`, `filter: drop-shadow`, degradados ni `backdrop-filter`. Los estados interactivos SHALL expresarse con opacidad del borde o un relleno blanco tenue.

#### Scenario: Hover sobre un botón
- **WHEN** el cursor pasa sobre un botón fantasma
- **THEN** aparece un relleno blanco al 8 % sin sombra

### Requirement: Legibilidad y accesibilidad sobre el mapa
El texto sobre el globo o el mapa SHALL ir en paneles con fondo `--color-overlay` y borde de 1 px. Todo texto necesario para entender un dato MUST medir al menos 12 px y cumplir contraste WCAG AA; `--color-dim-steel` MUST NOT usarse para texto legible.

#### Scenario: Panel sobre una capa clara
- **WHEN** un panel de controles queda sobre una zona clara de la imagen base
- **THEN** el texto sigue cumpliendo contraste AA gracias al fondo del panel

### Requirement: Badges de madurez monocromáticos
El badge de madurez SHALL distinguir los niveles por el trazo del borde (`VALIDATED` sólido, `PROVISIONAL` discontinuo, `BETA` punteado) e incluir siempre el texto del nivel.

#### Scenario: Comparar dos madureces
- **WHEN** se muestran juntas una capa `PROVISIONAL` y una `VALIDATED`
- **THEN** sus badges se distinguen por el texto y el trazo, sin usar color

### Requirement: Layout de pantalla completa
El globo o el mapa SHALL ocupar toda la ventana en `orbit-view`, `basin-map`, `temporal-lab` y `risk-dashboard`. Los controles SHALL flotar en el tercio izquierdo (máx. 450 px) en escritorio y en una hoja inferior deslizable en pantallas menores de 768 px. La barra superior SHALL ser transparente y alojar el widget `pass-countdown` en el extremo derecho.

#### Scenario: Pantalla de escritorio
- **WHEN** se abre `basin-map` en un monitor de 1440 px
- **THEN** el mapa ocupa toda la ventana y los controles flotan a la izquierda sin tapar más de un tercio del ancho

#### Scenario: Celular
- **WHEN** se abre la misma vista a 360 px
- **THEN** los controles aparecen en una hoja inferior y el mapa sigue ocupando la pantalla
