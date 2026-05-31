# Proyecto: lector

## Objetivo
Visor de textos orientado a la lectura (no edición), con búsqueda avanzada, traducción en contexto e imágenes de referencia.

## Estado del proyecto
- 🟡 En desarrollo — estructura base implementada, sin prueba visual aún

## Arquitectura
```
lector/
├── main.py              # entry point: python main.py [archivo.txt]
├── src/
│   ├── search.py        # lógica de los 4 modos de búsqueda (sin Qt)
│   ├── translation.py   # MyMemory API (traducción) + Pixabay API (imágenes)
│   └── viewer.py        # UI completa: LectorWindow, SearchBar, MarkerBar, TranslationDialog
├── tests/
│   ├── conftest.py
│   └── test_search.py   # 29 tests pytest (todos pasando)
└── requirements.txt
```

## Stack técnico
- **Python 3.10+** + **PyQt6** — UI de escritorio, estilo gedit
- **MyMemory API** — traducción EN→ES, gratuita sin API key
- **Pixabay API** — 3 imágenes por término (requiere `PIXABAY_API_KEY` env var)
- **pytest** — tests unitarios del módulo de búsqueda

## Funcionalidades implementadas
### Visor
- Texto con tipografía de lectura (Georgia 14pt, interlineado 160%, márgenes generosos)
- Fondo crema (#FAFAF7), sin bordes
- Abrir archivo vía botón o `python main.py archivo.txt`

### Búsqueda (Ctrl+F)
| Modo | Descripción |
|---|---|
| Simple | substring exacto, case-insensitive |
| Fuzzy | cada char → `char+`, encuentra "yeeees" buscando "yes" |
| Proximidad | dos términos A y B con gap < n chars entre ellos |
| OR | marca todas las instancias de A y de B por separado |

- Highlights con `setExtraSelections` (no modifica el documento)
- Match actual en rojo, resto en amarillo/azul/naranja según tipo
- Barra de marcadores (10px) a la derecha con posición de cada match
- Primer Enter: busca / Enter siguiente: navega al próximo match
- Botones ◀ ▶ para navegación explícita
- Contador "X / N" en la barra
- Cruz ✕ o Escape cierra la búsqueda y limpia highlights

### Traducción
- Click derecho sobre palabra → menú "Traducir"
- Popup con: palabra original, traducción EN→ES, 3 imágenes Pixabay
- Carga asíncrona (QThread) sin bloquear la UI

### Auto-scroll
- Botón ▶/⏸ en toolbar
- Slider de velocidad 1–10 (desde muy lento hasta escaneo rápido)
- Se detiene automáticamente al llegar al final

## Cómo correr
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Correr la app
python main.py
python main.py mi_texto.txt

# Correr tests
python -m pytest tests/ -v

# Variable de entorno para imágenes (opcional)
export PIXABAY_API_KEY="tu_key_aqui"
```

## Pendientes
- [ ] Probar la UI visualmente en pantalla
- [ ] Agregar `.venv` al `.gitignore`
- [ ] Tests de integración para la UI (opcional)
- [ ] Soporte para .pdf y .epub

## Notas
- `proximity_search`: el gap se mide desde el **fin** del primer término al **inicio** del segundo (no entre posiciones iniciales). Gap estrictamente < n.
- Las imágenes se traen en el mismo worker thread que la traducción (serial, no paralelo) para simplificar.
- `setExtraSelections` se usa para highlights — no modifica el documento, lo que evita corromper el formato al limpiar.
