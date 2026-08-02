#!/usr/bin/env python3
"""
Ranking de historias por frecuencia de palabras, sobre el índice invertido.

Dos modos de matcheo:
  stem  — 'whip' matchea whip/whips/whipping/whipped (tabla word_index)
  exact — 'whip' matchea solo 'whip'                 (tabla exact_index)

Con varias palabras exige que estén TODAS (AND) y ordena por la suma de
ocurrencias.

Uso:
  python3 word_rank.py whip --top 20
  python3 word_rank.py castle dungeon --exact --per-1k
"""

import os, sqlite3, argparse
import snowballstemmer

INDEX_DB = os.path.expanduser('~/corpus-historias/word_index.db')

_stemmer = snowballstemmer.stemmer('english')


def stem(word):
    return _stemmer.stemWord(word.lower())


def has_exact_index(conn):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exact_index'"
    ).fetchone()
    return row is not None


def ensure_story_totals(conn):
    """Total de palabras por historia, derivado del propio índice.

    Se usa para normalizar por longitud. `stories.word_count` no sirve: solo
    está poblado en ~38% del corpus. Tarda unos segundos, así que se cachea
    en una tabla dentro del índice.
    """
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_totals'"
    ).fetchone():
        return
    conn.execute('CREATE TABLE story_totals (story_id INTEGER PRIMARY KEY, total INTEGER)')
    conn.execute('''
        INSERT INTO story_totals (story_id, total)
        SELECT story_id, SUM(count) FROM word_index GROUP BY story_id
    ''')
    conn.commit()


def word_counts(conn, words, exact=False):
    """{story_id: ocurrencias sumadas}, solo historias que tienen TODAS las palabras."""
    if not words:
        return {}
    if exact:
        if not has_exact_index(conn):
            raise RuntimeError(
                "El índice no tiene búsqueda exacta. Reconstruilo con:\n"
                "  python build_index.py"
            )
        table, terms = 'exact_index', [w.lower() for w in words]
    else:
        table, terms = 'word_index', [stem(w) for w in words]

    terms = list(dict.fromkeys(terms))  # dedup, si no HAVING cuenta de menos
    placeholders = ','.join('?' * len(terms))
    rows = conn.execute(f'''
        SELECT story_id, SUM(count)
        FROM {table}
        WHERE word IN ({placeholders})
        GROUP BY story_id
        HAVING COUNT(DISTINCT word) = ?
    ''', (*terms, len(terms))).fetchall()
    return dict(rows)


def stories_with_words(index_db, words, exact=False):
    """IDs de historias cuyo cuerpo contiene todas las palabras."""
    conn = sqlite3.connect(index_db)
    try:
        return set(word_counts(conn, words, exact))
    finally:
        conn.close()


def rank_by_words(index_db, words, exact=False, top_n=50, by_density=False):
    """Historias ordenadas por ocurrencias (o por ocurrencias/1000 palabras).

    Devuelve dicts con: id, hits, total, per_1k
    """
    conn = sqlite3.connect(index_db)
    try:
        counts = word_counts(conn, words, exact)
        if not counts:
            return []
        ensure_story_totals(conn)
        totals = dict(conn.execute('SELECT story_id, total FROM story_totals'))
    finally:
        conn.close()

    results = []
    for sid, hits in counts.items():
        total = totals.get(sid) or 0
        results.append({
            'id': sid,
            'hits': hits,
            'total': total,
            'per_1k': (hits / total * 1000) if total else 0.0,
        })

    results.sort(key=lambda r: r['per_1k' if by_density else 'hits'], reverse=True)
    for i, r in enumerate(results[:top_n], start=1):
        r['rank'] = i
    return results[:top_n]


def main():
    p = argparse.ArgumentParser(description='Ranking por frecuencia de palabras')
    p.add_argument('words', nargs='+')
    p.add_argument('--index', default=INDEX_DB)
    p.add_argument('--db', default=os.path.expanduser('~/corpus-historias/stories.db'))
    p.add_argument('--top', type=int, default=20)
    p.add_argument('--exact', action='store_true', help='palabra exacta, sin stemming')
    p.add_argument('--per-1k', action='store_true', help='ordenar por densidad')
    args = p.parse_args()

    results = rank_by_words(args.index, args.words, args.exact, args.top, args.per_1k)
    if not results:
        print("Ninguna historia contiene todas esas palabras.")
        return

    conn = sqlite3.connect(args.db)
    titles = dict(conn.execute('SELECT id, title FROM stories'))
    conn.close()

    modo = 'exacta' if args.exact else 'con stemming'
    orden = 'por cada 1000 palabras' if args.per_1k else 'ocurrencias totales'
    print(f"\nTop {args.top} para {args.words} ({modo}, ordenado por {orden})\n")
    print(f"{'#':>3}  {'Veces':>6}  {'/1000':>6}  Título")
    print("─" * 70)
    for r in results:
        print(f"{r['rank']:3d}  {r['hits']:6d}  {r['per_1k']:6.2f}  "
              f"{(titles.get(r['id']) or '?')[:45]}")


if __name__ == '__main__':
    main()
