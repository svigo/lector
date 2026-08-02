#!/usr/bin/env python3
"""
Calcula métricas de texto de cada historia y las guarda en stories.db.
Uso: python3 compute_text_features.py --stories-dir stories/resto/ [--db stories.db]

Métricas calculadas:
  word_count     — total de palabras en el contenido (sin header)
  unique_words   — palabras únicas (vocabulario)
  vocab_diversity — unique_words / sqrt(word_count)  (índice de Guiraud)
"""

import os, glob, re, math, sqlite3, argparse

SEPARATOR = re.compile(r'^-{10,}', re.MULTILINE)
WORD = re.compile(r'[a-zA-Z]+')


def story_content(path):
    """Devuelve solo el contenido de la historia (sin el header ID/Título/etc.)."""
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    m = SEPARATOR.search(text)
    return text[m.end():] if m else text


def text_features(text):
    words = WORD.findall(text.lower())
    total = len(words)
    unique = len(set(words))
    diversity = unique / math.sqrt(total) if total > 0 else 0.0
    return total, unique, diversity


def get_story_id(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(300)
        m = re.search(r'\bID:\s*(\d+)', head)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def ensure_columns(conn):
    cols = {row[1] for row in conn.execute('PRAGMA table_info(stories)')}
    for col, typ in [('word_count', 'INTEGER'), ('unique_words', 'INTEGER'), ('vocab_diversity', 'REAL')]:
        if col not in cols:
            conn.execute(f'ALTER TABLE stories ADD COLUMN {col} {typ}')
    conn.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stories-dir', default=os.path.expanduser('~/corpus-historias/stories/resto'))
    p.add_argument('--db', default=os.path.expanduser('~/corpus-historias/stories.db'))
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_columns(conn)

    paths = sorted(glob.glob(os.path.join(args.stories_dir, '**', '*.txt'), recursive=True))
    print(f"{len(paths)} archivos encontrados en {args.stories_dir}")

    # IDs ya procesados
    done = {row[0] for row in conn.execute(
        'SELECT id FROM stories WHERE word_count IS NOT NULL')}
    print(f"{len(done)} ya procesados, {len(paths) - len(done)} pendientes")

    ok = skip = err = 0
    for i, path in enumerate(paths):
        sid = get_story_id(path)
        if sid is None or sid in done:
            skip += 1
            continue
        try:
            content = story_content(path)
            wc, uw, vd = text_features(content)
            conn.execute(
                'UPDATE stories SET word_count=?, unique_words=?, vocab_diversity=? WHERE id=?',
                (wc, uw, vd, sid)
            )
            ok += 1
            if ok % 500 == 0:
                conn.commit()
                pct = (i + 1) / len(paths) * 100
                print(f"  {ok} procesados ({pct:.0f}%)...")
        except Exception as e:
            err += 1

    conn.commit()
    conn.close()
    print(f"\nFin. Procesados: {ok}  Saltados: {skip}  Errores: {err}")

    # Muestra ejemplo de los valores calculados
    conn2 = sqlite3.connect(args.db)
    print("\nEjemplo (top 5 por diversidad de vocabulario):")
    print(f"  {'Título':<40} {'Palabras':>8} {'Únicas':>7} {'Diversidad':>10}")
    print("  " + "─" * 68)
    for row in conn2.execute('''
        SELECT title, word_count, unique_words, vocab_diversity
        FROM stories WHERE vocab_diversity IS NOT NULL
        ORDER BY vocab_diversity DESC LIMIT 5
    '''):
        print(f"  {(row[0] or '?'):<40} {row[1]:>8,} {row[2]:>7,} {row[3]:>10.1f}")
    conn2.close()


if __name__ == '__main__':
    main()
