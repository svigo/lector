# Proyecto: lector

## Objetivo
Visor de textos orientado a la lectura (no edición), con búsqueda avanzada, traducción en contexto e imágenes de referencia.

## Estado del proyecto
- 🟢 Funcional — todas las features core implementadas y probadas visualmente

## Arquitectura
```
lector/
├── main.py                  # entry point: python main.py [archivo.txt]
├── reflow_stories.py        # script batch para corregir hard-wraps en .txt
├── src/
│   ├── search.py            # 4 modos de búsqueda (sin Qt)
│   ├── translation.py       # MyMemory + Pixabay + Wikipedia fallback + spell correction
│   └── viewer.py            # UI completa PyQt6
├── tests/
│   ├── conftest.py
│   └── test_search.py       # 29 tests pytest (todos pasando)
├── story_classifier/        # pipeline del corpus de historias (movido desde machinelearning)
│   ├── scraper.py           # descarga historias + metadatos → stories.db
│   ├── build_index.py       # índice invertido de palabras → word_index.db
│   ├── compute_text_features.py  # features de texto por historia → stories.db
│   ├── classifier.py        # clustering TF-IDF + KMeans → clasificacion.csv/.pkl
│   ├── refine.py            # re-clustering de un subconjunto
│   ├── similarity.py        # similitud TF-IDF entre historias → similarity_cache.pkl
│   ├── ranker.py            # RANKING: señales + pesos → top N historias
│   ├── ranker_gui.py        # GUI "Calibrador de Ranking" (Tkinter)
│   ├── tagger_gui.py        # GUI de etiquetado manual
│   └── stopwords_fiction.txt
└── requirements.txt
```

## Corpus de historias (`~/corpus-historias/`)
Los datos **no están en el repo** (~600 MB). Todos los scripts los referencian por ruta
absoluta con `os.path.expanduser('~/corpus-historias/...')`, así que funcionan desde
cualquier directorio.

| Archivo | Qué es |
|---|---|
| `stories/resto/` | 10543 historias en `.txt` (ya pasadas por `reflow_stories.py`) |
| `stories.db` | SQLite: metadatos, rating, votos, shelves, features de texto |
| `word_index.db` | índice invertido para el tagger |
| `similarity_cache.pkl` | matriz de similitud precomputada |
| `clasificacion*.csv/.pkl` | salida del clustering |

## Stack técnico
- **Python 3.10+** + **PyQt6** — UI de escritorio, estilo gedit
- **MyMemory API** — traducción EN→ES, gratuita sin API key
- **Pixabay API** — imágenes (requiere `PIXABAY_API_KEY` en `~/.profile`)
- **Wikipedia API** — fallback de imágenes cuando Pixabay da 0 resultados
- **pyspellchecker** — corrección de typos antes de traducir y buscar imágenes
- **pytest** — tests unitarios del módulo de búsqueda
- **numpy / scipy / scikit-learn / pandas** — pipeline del corpus (TF-IDF, KMeans, similitud)
- **snowballstemmer** — stemming para el índice de palabras y el tagger
- **beautifulsoup4** — parseo HTML del scraper
- **Tkinter** — GUIs del pipeline (`ranker_gui`, `tagger_gui`); el visor es PyQt6

## Funcionalidades implementadas

### Visor
- Tipografía Georgia 14pt, interlineado 160%, márgenes 60px, fondo crema
- Reflow automático de hard-wraps al cargar (une líneas que no terminan en `.?!`)
- Abrir con `Ctrl+O` o botón

### Búsqueda (Ctrl+F)
| Modo | Descripción |
|---|---|
| Simple | substring exacto, case-insensitive |
| Fuzzy | cada char → `char+`, encuentra "yeeees" buscando "yes" |
| Proximidad | A y B con gap < n chars — navega por pares (no términos) |
| OR | todas las instancias de A y de B |

- Tab cicla modos desde el input (Shift+Tab: atrás)
- En modos de 2 campos: Tab desde input_a va a input_b
- Highlights con `setExtraSelections` (no modifica el documento)
- Match actual en rojo; resto: amarillo/azul/naranja según tipo
- Barra de marcadores (10px) a la derecha — clampeada para no perderse en bordes
- Enter: busca / Enter siguiente: navega al próximo match
- Botones ◀/▶: si el término cambió desde la última búsqueda, buscan de nuevo; si no cambió, navegan (misma lógica que Enter, unificada en `_handle_nav`)
- F3 / Shift+F3: siguiente / anterior match
- ✕ o Escape cierra y limpia
- `Ctrl+C` copia la selección del texto al portapapeles

### Traducción
- Click derecho traduce directo (sin menú, ya no hay más de una opción)
- Si hay una frase seleccionada, traduce la selección completa; si no, la palabra bajo el cursor
- Spell correction antes de traducir e imágenes (solo aplica a palabra suelta; en frases no encuentra corrección y devuelve la frase intacta)
- Traducción: MyMemory primero, si no da resultado usable cae a Lingva (mirror de Google Translate, sin API key)
- Slang: definición de Urban Dictionary (sin API key), se muestra solo si hay resultado — útil para términos que MyMemory/Lingva no manejan bien
- Popup: palabra original, nota "typo corregido → X" si hubo corrección, traducción ES aparece apenas llega (no espera al resto), definición de slang después, 3 imágenes al final (lo más lento)
- Carga asíncrona (QThread) — `_LoadingWorker` emite en orden `translated` → `slang_done` → `images_done`, cada uno actualiza su parte de la UI sin bloquear a los demás

### Auto-scroll
- `Ctrl+Space` activa/desactiva por completo
- `Space` (sola) pausa/reanuda el auto-scroll **solo si ya está activo** (botón alterna "⏸ Pausar" / "▶ Reanudar (Espacio)"); el slider queda visible mientras está pausado
- Al activar aparece slider de velocidad 1–10
- `+` / `-` ajustan velocidad (solo cuando activo)
- Se detiene al llegar al final

### Teclas globales (foco-agnósticas)
Implementadas con un `eventFilter` a nivel de `QApplication` (guardado con `isActiveWindow()` para no interferir con diálogos modales):
- `↑` / `↓` scrollean el texto una línea por pulsación **sin importar el foco**, salvo cuando el foco está en el combo de modo o el spinbox `n` (ahí conservan su navegación nativa)
- `Enter` va al siguiente match si hay búsqueda activa; dentro de los inputs de búsqueda se mantiene el `returnPressed` (1er Enter busca, siguientes navegan)
- `Space` pausa/reanuda auto-scroll (ver arriba)

### Ranking de historias (`story_classifier/ranker.py`)
Ordena el corpus por calidad estimada. Cada señal se normaliza a [0,1] con
`percentile_rank` y se combina con pesos configurables (score = Σ peso·señal / Σ pesos).

| Señal | Cómo se calcula |
|---|---|
| `bayesian` | rating suavizado hacia la media global: `v/(v+10)·r + 10/(v+10)·media` — evita que 1 voto de 10 gane |
| `engagement` | votos / lectores (se muestra en ‰) |
| `shelves` | cantidad de estanterías donde fue guardada |
| `quality` | calidad agregada de las estanterías que la contienen |
| `longevity` | lectores / años desde la publicación |
| `length` | word_count |
| `vocab` | diversidad de vocabulario |

- CLI: `python3 ranker.py --top 20 [--db ...]`
- GUI: `ranker_gui.py` — sliders para calibrar los pesos en vivo, filtro por similitud
  (`similarity.py`) y **abre la historia elegida en el lector** (`.venv/bin/python main.py`).
- `tagger_gui.py` también lanza el lector para leer mientras se etiqueta.

### Atajos completos
| Atajo | Acción |
|---|---|
| `Ctrl+O` | Abrir archivo |
| `Ctrl+F` | Búsqueda |
| `Escape` | Cerrar búsqueda |
| `F3` | Siguiente match |
| `Shift+F3` | Match anterior |
| `Enter` | Siguiente match (foco-agnóstico, si hay búsqueda activa) |
| `↑` / `↓` | Scrollear texto (foco-agnóstico) |
| `Ctrl+Space` | Activar/desactivar auto-scroll |
| `Space` | Pausar/reanudar auto-scroll (solo si está activo) |
| `+` / `-` | Velocidad auto-scroll (solo activo) |
| `Tab` | Ciclar modo de búsqueda |

## Cómo correr
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py
python main.py archivo.txt
python -m pytest tests/ -v

# Pixabay key (ya configurada en ~/.profile)
export PIXABAY_API_KEY="..."

# Log de imágenes/traducción
tail -f /tmp/lector.log
```

### Ranking (mismo venv que el visor)
```bash
source .venv/bin/activate
cd story_classifier
python ranker.py --top 20     # CLI
python ranker_gui.py          # GUI de calibración de pesos
python tagger_gui.py          # GUI de etiquetado
```

## Pendientes
- [ ] Tests de integración para la UI
- [ ] Soporte para .pdf y .epub
- [ ] Quitar logging de debug antes de distribución
- [ ] Commit de la mudanza en ambos repos (borrado ya staged en `machinelearning`)

## Notas
- `proximity_search`: gap = fin del primero al inicio del segundo, estrictamente < n. Navegación por pares (label='a'), highlights muestran ambos términos.
- `_nav_matches` separa los matches navegables de los highlights (relevante en Proximidad).
- `setExtraSelections` para highlights — no corrompe el documento al limpiar.
- Teclas globales vía `eventFilter` en `QApplication` (instalado en `__init__`). `_scroll_lines` usa `fontMetrics().height()` como paso. `_toggle_autoscroll_pause` devuelve `True` solo si el auto-scroll está activo (botón checked), distinguiendo pausa (timer parado, botón sigue checked) de desactivación (`Ctrl+Space`).
- `PIXABAY_API_KEY` en `~/.profile` (no en `.bashrc` que tiene guard de shell interactivo).
- Fix: los botones ◀/▶ antes navegaban matches viejos aunque el término de búsqueda hubiera cambiado (solo Enter re-buscaba). Ahora `SearchBar._handle_nav(direction)` centraliza la lógica de "¿cambió el término? buscar : navegar" para Enter y ambos botones.
- Lanzador en `~/Escritorio/lector.desktop`.
- `reflow_stories.py` ya procesó 10543 historias en `~/corpus-historias/stories/resto/`.
- **Mudanza (2026-08-02)**: `story_classifier/` se movió desde `~/proyectos/machinelearning/`
  a este proyecto — el corpus es lo que el lector lee y en machinelearning (misceláneo) era
  un huésped. En machinelearning quedó el borrado staged, sin commitear. La historia git de
  esos archivos no cruza entre repos: para arqueología, ver `git log` de machinelearning.
- Los scripts usan rutas absolutas a `~/corpus-historias`, por eso la mudanza no rompió nada
  (verificado corriendo `ranker.py --top 5` desde la nueva ubicación).
