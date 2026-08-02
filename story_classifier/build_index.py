#!/usr/bin/env python3
"""
Construye un índice invertido palabra → (historia, cantidad) en word_index.db.
Permite que el tagger previsualice reglas en milisegundos en vez de releer 10k archivos.

Tablas:
  word_index      stems Snowball  ('whip' agrupa whip/whips/whipping/whipped)
  exact_index     formas literales tal como aparecen en el texto
  story_totals    total de palabras por historia (para normalizar por longitud)

Uso: python3 build_index.py --stories-dir stories/resto/ [--index word_index.db]
"""

import os, glob, re, sqlite3, argparse, time
from collections import Counter
import snowballstemmer

SEP = re.compile(r'-{10,}')
WORD_RE = re.compile(r'[a-z]+')

_stemmer = snowballstemmer.stemmer('english')
_stem_cache = {}

def stem(w):
    s = _stem_cache.get(w)
    if s is None:
        s = _stemmer.stemWord(w)
        _stem_cache[w] = s
    return s


def story_body(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    m = SEP.search(text)
    return text[m.end():].lower() if m else text.lower()


def story_id_from_file(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        head = f.read(300)
    m = re.search(r'\bID:\s*(\d+)', head)
    return int(m.group(1)) if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stories-dir', default=os.path.expanduser('~/corpus-historias/stories/resto'))
    p.add_argument('--index', default=os.path.expanduser('~/corpus-historias/word_index.db'))
    args = p.parse_args()

    # Se construye aparte y se renombra al final: si esto se corta a la mitad,
    # el índice viejo sigue usable.
    tmp_index = args.index + '.tmp'
    if os.path.exists(tmp_index):
        os.remove(tmp_index)

    conn = sqlite3.connect(tmp_index)
    conn.execute('PRAGMA journal_mode=OFF')
    conn.execute('PRAGMA synchronous=OFF')
    conn.execute('CREATE TABLE word_index (word TEXT, story_id INTEGER, count INTEGER)')
    conn.execute('CREATE TABLE exact_index (word TEXT, story_id INTEGER, count INTEGER)')
    conn.execute('CREATE TABLE indexed_stories (story_id INTEGER PRIMARY KEY)')

    paths = sorted(glob.glob(os.path.join(args.stories_dir, '**', '*.txt'), recursive=True))
    print(f"{len(paths)} archivos a indexar...")

    t0 = time.time()
    batch, exact_batch = [], []
    n_stories = 0
    for i, path in enumerate(paths):
        sid = story_id_from_file(path)
        if sid is None:
            continue
        words = WORD_RE.findall(story_body(path))
        exact_counts = Counter(words)
        counts = Counter()
        for w, c in exact_counts.items():
            counts[stem(w)] += c
        batch.extend((w, sid, c) for w, c in counts.items())
        exact_batch.extend((w, sid, c) for w, c in exact_counts.items())
        conn.execute('INSERT OR IGNORE INTO indexed_stories (story_id) VALUES (?)', (sid,))
        n_stories += 1

        if len(batch) >= 50000:
            conn.executemany('INSERT INTO word_index (word, story_id, count) VALUES (?,?,?)', batch)
            batch.clear()
        if len(exact_batch) >= 50000:
            conn.executemany('INSERT INTO exact_index (word, story_id, count) VALUES (?,?,?)', exact_batch)
            exact_batch.clear()
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(paths)} archivos ({(i+1)/len(paths)*100:.0f}%)...")

    if batch:
        conn.executemany('INSERT INTO word_index (word, story_id, count) VALUES (?,?,?)', batch)
    if exact_batch:
        conn.executemany('INSERT INTO exact_index (word, story_id, count) VALUES (?,?,?)', exact_batch)
    conn.commit()

    print("Creando índices sobre 'word' (puede tardar)...")
    conn.execute('CREATE INDEX idx_word ON word_index (word)')
    conn.execute('CREATE INDEX idx_exact_word ON exact_index (word)')
    conn.commit()

    print("Calculando total de palabras por historia...")
    conn.execute('CREATE TABLE story_totals (story_id INTEGER PRIMARY KEY, total INTEGER)')
    conn.execute('''
        INSERT INTO story_totals (story_id, total)
        SELECT story_id, SUM(count) FROM word_index GROUP BY story_id
    ''')
    conn.commit()

    n_rows = conn.execute('SELECT COUNT(*) FROM word_index').fetchone()[0]
    n_words = conn.execute('SELECT COUNT(DISTINCT word) FROM word_index').fetchone()[0]
    n_exact = conn.execute('SELECT COUNT(DISTINCT word) FROM exact_index').fetchone()[0]
    conn.close()

    os.replace(tmp_index, args.index)

    size_mb = os.path.getsize(args.index) / 1024 / 1024
    dt = time.time() - t0
    print(f"\nÍndice construido en {dt:.0f}s:")
    print(f"  {n_stories:,} historias indexadas")
    print(f"  {n_words:,} stems únicos")
    print(f"  {n_exact:,} formas literales únicas")
    print(f"  {n_rows:,} entradas")
    print(f"  {size_mb:.0f} MB → {args.index}")


if __name__ == '__main__':
    main()
