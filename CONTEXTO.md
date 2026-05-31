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
└── requirements.txt
```

## Stack técnico
- **Python 3.10+** + **PyQt6** — UI de escritorio, estilo gedit
- **MyMemory API** — traducción EN→ES, gratuita sin API key
- **Pixabay API** — imágenes (requiere `PIXABAY_API_KEY` en `~/.profile`)
- **Wikipedia API** — fallback de imágenes cuando Pixabay da 0 resultados
- **pyspellchecker** — corrección de typos antes de traducir y buscar imágenes
- **pytest** — tests unitarios del módulo de búsqueda

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
- F3 / Shift+F3: siguiente / anterior match
- ✕ o Escape cierra y limpia

### Traducción
- Click derecho → "Traducir"
- Spell correction antes de traducir e imágenes
- Popup: palabra original, nota "typo corregido → X" si hubo corrección, traducción ES, 3 imágenes
- Carga asíncrona (QThread)

### Auto-scroll
- `Ctrl+Space` activa/pausa
- Al activar aparece slider de velocidad 1–10
- `+` / `-` ajustan velocidad (solo cuando activo)
- Se detiene al llegar al final

### Atajos completos
| Atajo | Acción |
|---|---|
| `Ctrl+O` | Abrir archivo |
| `Ctrl+F` | Búsqueda |
| `Escape` | Cerrar búsqueda |
| `F3` | Siguiente match |
| `Shift+F3` | Match anterior |
| `Ctrl+Space` | Activar/pausar auto-scroll |
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

## Pendientes
- [ ] Tests de integración para la UI
- [ ] Soporte para .pdf y .epub
- [ ] Quitar logging de debug antes de distribución

## Notas
- `proximity_search`: gap = fin del primero al inicio del segundo, estrictamente < n. Navegación por pares (label='a'), highlights muestran ambos términos.
- `_nav_matches` separa los matches navegables de los highlights (relevante en Proximidad).
- `setExtraSelections` para highlights — no corrompe el documento al limpiar.
- `PIXABAY_API_KEY` en `~/.profile` (no en `.bashrc` que tiene guard de shell interactivo).
- Lanzador en `~/Escritorio/lector.desktop`.
- `reflow_stories.py` ya procesó 10543 historias en `/proyectos/machinelearning/stories/resto/`.
