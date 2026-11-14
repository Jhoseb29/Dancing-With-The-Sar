## mapa json con todas las urls y accesos que encontramos:

./data-map.json

### backend
- define la arquitectura y modulos, usaremos python con fast api para modulos que lo requieran, servicios de ia externo, analisis y procesamiento de datos.

### frontend
- para el frontend usaremos la estructura core, feature, layout y shared. para cada feature tendremos 3 archivos, .ts, .scss, .html. 

- angular 22 con signals de forma nativa, ngrx si es necesario, standalone components, pipes, lazy loading.

- patrones como dump smart component.

### integracias de harnes

Habras 2 harness:

1. Analista de los datos en base a ./data-map.json, creara skills analizando la base al de los datos, tambien debe validar lo encontrado, usar scripts dentro de las skills, dar un score y juzgar su analisis el objetivo es que en base a este input con ayuda del harness que creamos nos de un output para usar esta data en el siguiente harness.

2. Interpretador del output y ahora genera un otput mejorado, entendible para todo tipo de usuario y didactico. Aca debe ser capaz que con el output del anterio harness cree el output esperado y se entrende nuestro harness con toda la data y luego lo guardaremos en un set de datos la data ya entrenada e interpretada.

## constraints

- respetar la estructura de carpetas y 3 archivos del frontend

- usar solid para el backend

- 12 factor apps para todo el proyecto

- monolito modular, respetar los modulos.

- tu no debes hacer los commits