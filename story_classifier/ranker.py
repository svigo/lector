#!/usr/bin/env python3
"""
Ranker de historias — score compuesto normalizado por percentil.

Señales:
  rating     — Bayesian rating (penaliza pocos votos)
  engagement — % de lectores que votaron (historia que engancha)
  shelves    — cantidad de shelves donde aparece (impacto)
  quality    — shelves con nombres de calidad (curación humana)
  longevity  — lectores totales / años desde publicación (clásico vs trending)

Uso:
  python3 ranker.py [--db stories.db] [--top 20]
  python3 ranker.py --w-rating 2 --w-shelves 0.5 --top 50
"""

import sqlite3, argparse, os
import numpy as np
from datetime import datetime

QUALITY_KEYWORDS = {
    'best', 'classic', 'favorite', 'favourite', 'fav', 'favs', 'top',
    'must', 'love', 'great', 'excellent', 'recommended', 'gems',
    'masterpiece', 'perfect', 'only', 'picks', 'gold', 'all', 'primo',
}


def percentile_rank(values):
    """Normaliza a [0,1] por rango percentil. Robusto a outliers."""
    arr = np.array(values, dtype=float)
    nan_mask = np.isnan(arr)
    result = np.zeros(len(arr))
    valid_idx = np.where(~nan_mask)[0]
    valid = arr[~nan_mask]
    if len(valid) < 2:
        return result
    order = valid.argsort()
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(len(valid))
    result[valid_idx] = ranks / (len(valid) - 1)
    return result


def parse_date(s):
    if not s:
        return None
    for fmt in ('%b %d, %Y', '%B %d, %Y', '%b %Y', '%B %Y'):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def load_data(conn, allowed_ids=None):
    query = '''
        SELECT s.id, s.title, s.author,
               s.rating, s.votes,
               s.readers_total, s.readers_month,
               s.published, s.size_kb,
               s.word_count, s.vocab_diversity,
               COUNT(sh.id) AS n_shelves
        FROM stories s
        LEFT JOIN shelves sh ON sh.story_id = s.id
        WHERE s.scraped_at IS NOT NULL AND s.scraped_at != 'NOT_FOUND'
    '''
    params = ()
    if allowed_ids is not None:
        placeholders = ','.join('?' * len(allowed_ids))
        query += f' AND s.id IN ({placeholders})'
        params = tuple(allowed_ids)
    query += ' GROUP BY s.id'
    stories = conn.execute(query, params).fetchall()

    # Shelf quality por historia: contar shelves con keywords positivas
    shelf_quality = {}
    for row in conn.execute('SELECT story_id, shelf_name FROM shelves WHERE shelf_name IS NOT NULL'):
        words = set(row[1].lower().split())
        if words & QUALITY_KEYWORDS:
            shelf_quality[row[0]] = shelf_quality.get(row[0], 0) + 1

    return stories, shelf_quality


def compute_signals(stories, shelf_quality):
    now = datetime.now()

    rated = [r['rating'] for r in stories if r['rating'] and (r['votes'] or 0) >= 3]
    global_mean = sum(rated) / len(rated) if rated else 5.0
    min_votes = 10

    ids, titles, authors = [], [], []
    raw = {k: [] for k in ('bayesian', 'engagement', 'shelves', 'quality', 'longevity', 'length', 'vocab')}

    for s in stories:
        ids.append(s['id'])
        titles.append(s['title'] or '?')
        authors.append(s['author'] or '?')

        v = s['votes'] or 0
        r = s['rating'] or global_mean
        raw['bayesian'].append(
            (v / (v + min_votes)) * r + (min_votes / (v + min_votes)) * global_mean
        )

        readers = max(s['readers_total'] or 0, 1)
        raw['engagement'].append(v / readers)

        raw['shelves'].append(s['n_shelves'] or 0)

        raw['quality'].append(shelf_quality.get(s['id'], 0))

        pub = parse_date(s['published'])
        age_years = max((now - pub).days / 365.25, 0.1) if pub else 10.0
        raw['longevity'].append((s['readers_total'] or 0) / age_years)

        raw['length'].append(s['word_count'] or 0)
        raw['vocab'].append(s['vocab_diversity'] or 0.0)

    return ids, titles, authors, raw


def rank_stories(db_path, weights, top_n, allowed_ids=None):
    if allowed_ids is not None and not allowed_ids:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    stories, shelf_quality = load_data(conn, allowed_ids)
    conn.close()

    if not stories:
        print("No hay historias en la DB todavía.")
        return []

    ids, titles, authors, raw = compute_signals(stories, shelf_quality)

    # Normalizar cada señal a [0,1]
    norm = {k: percentile_rank(raw[k]) for k in raw}

    total_w = sum(weights.values()) or 1
    scored = []
    for i in range(len(ids)):
        score = sum(weights[k] * norm[k][i] for k in weights) / total_w
        scored.append({
            'rank':       0,
            'score':      score,
            'id':         ids[i],
            'title':      titles[i],
            'author':     authors[i],
            'bayesian':   raw['bayesian'][i],
            'engagement': raw['engagement'][i] * 1000,  # en ‰
            'shelves':    int(raw['shelves'][i]),
            'quality':    int(raw['quality'][i]),
            'longevity':  raw['longevity'][i],
            'length':     int(raw['length'][i]),
            'vocab':      raw['vocab'][i],
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    for i, s in enumerate(scored):
        s['rank'] = i + 1

    return scored[:top_n]


def main():
    p = argparse.ArgumentParser(description='Ranker de historias')
    p.add_argument('--db',           default=os.path.expanduser('~/corpus-historias/stories.db'))
    p.add_argument('--top',          type=int,   default=20)
    p.add_argument('--w-rating',     type=float, default=1.0)
    p.add_argument('--w-engagement', type=float, default=1.0)
    p.add_argument('--w-shelves',    type=float, default=1.0)
    p.add_argument('--w-quality',    type=float, default=1.0)
    p.add_argument('--w-longevity',  type=float, default=1.0)
    p.add_argument('--w-length',     type=float, default=1.0)
    p.add_argument('--w-vocab',      type=float, default=1.0)
    args = p.parse_args()

    weights = {
        'bayesian':   args.w_rating,
        'engagement': args.w_engagement,
        'shelves':    args.w_shelves,
        'quality':    args.w_quality,
        'longevity':  args.w_longevity,
        'length':     args.w_length,
        'vocab':      args.w_vocab,
    }

    results = rank_stories(args.db, weights, args.top)
    if not results:
        return

    print(f"\nTop {args.top} — pesos: rating={weights['bayesian']} eng={weights['engagement']} "
          f"shelves={weights['shelves']} quality={weights['quality']} longevity={weights['longevity']}\n")
    print(f"{'#':>3}  {'Score':>6}  {'Rating':>6}  {'Eng‰':>5}  {'Shelf':>5}  {'Qual':>4}  Título")
    print("─" * 85)
    for s in results:
        print(f"{s['rank']:3d}  {s['score']:.4f}  {s['bayesian']:6.2f}  "
              f"{s['engagement']:5.2f}  {s['shelves']:5d}  {s['quality']:4d}  "
              f"{s['title'][:40]}")


if __name__ == '__main__':
    main()
