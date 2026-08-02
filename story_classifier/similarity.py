#!/usr/bin/env python3
"""
Motor de similitud entre historias. Combina tres señales:
  - tags     → Jaccard (métrica real)
  - shelves  → coseno ponderado por IDF semántico × 1/log(tamaño)  (collaborative filtering)
  - synopsis → coseno TF-IDF (contenido)

El IDF semántico agrupa nombres de shelf sinónimos ("to read"/"reading"/"unread")
con embeddings, para que los shelves organizacionales pesen poco.

Uso:
  python3 similarity.py --build                 # construye el caché (tarda)
  python3 similarity.py --id 72 --k 10          # vecinas de la historia 72
  python3 similarity.py --id 72 --k 10 --w-tags 1 --w-shelf 2 --w-syn 1
"""

import os, sys, sqlite3, pickle, argparse, math
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

CORPUS = os.path.expanduser('~/corpus-historias')
DEFAULT_DB = os.path.join(CORPUS, 'stories.db')
DEFAULT_CACHE = os.path.join(CORPUS, 'similarity_cache.pkl')


# ── construcción del caché ────────────────────────────────────────────────

def build_cache(db_path, cache_path, shelf_cluster_threshold=0.45):
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import AgglomerativeClustering

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Historias válidas (scrapeadas)
    rows = conn.execute("""
        SELECT id, COALESCE(title,'') title, COALESCE(author,'') author,
               COALESCE(synopsis,'') synopsis
        FROM stories
        WHERE scraped_at IS NOT NULL AND scraped_at != 'NOT_FOUND'
        ORDER BY id
    """).fetchall()
    ids = [r['id'] for r in rows]
    id_to_idx = {sid: i for i, sid in enumerate(ids)}
    n = len(ids)
    titles = {r['id']: r['title'] for r in rows}
    authors = {r['id']: r['author'] for r in rows}
    print(f"{n} historias")

    # ── TAGS → matriz binaria sparse ─────────────────────────────────────
    tag_rows = conn.execute('SELECT story_id, tag FROM tags').fetchall()
    tag_list = sorted({t for _, t in tag_rows})
    tag_to_col = {t: j for j, t in enumerate(tag_list)}
    ti, tj = [], []
    for sid, tag in tag_rows:
        if sid in id_to_idx:
            ti.append(id_to_idx[sid]); tj.append(tag_to_col[tag])
    tag_matrix = sparse.csr_matrix((np.ones(len(ti)), (ti, tj)), shape=(n, len(tag_list)))
    tag_count = np.asarray(tag_matrix.sum(axis=1)).flatten()  # |tags| por historia
    print(f"tags: {len(tag_list)} únicos, {tag_matrix.nnz} asignaciones")

    # ── SHELVES → IDF semántico + matriz ponderada ───────────────────────
    shelf_rows = conn.execute("""
        SELECT story_id, shelf_name, username, shelf_url FROM shelves
        WHERE shelf_name IS NOT NULL
    """).fetchall()
    conn.close()

    # cada shelf-instancia única = (username, shelf_url)
    shelf_key = {}
    shelf_name_of = {}
    shelf_members = {}  # shelf_idx -> set(story_idx)
    for sid, name, user, url in shelf_rows:
        if sid not in id_to_idx:
            continue
        key = (user, url)
        if key not in shelf_key:
            shelf_key[key] = len(shelf_key)
            shelf_name_of[shelf_key[key]] = name
        sidx = shelf_key[key]
        shelf_members.setdefault(sidx, set()).add(id_to_idx[sid])
    n_shelves = len(shelf_key)
    print(f"shelves: {n_shelves} instancias únicas")

    # embeddings de nombres de shelf únicos → clusters semánticos
    unique_names = sorted({shelf_name_of[s] for s in range(n_shelves)})
    print(f"embeddings de {len(unique_names)} nombres de shelf...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    emb = model.encode(unique_names, show_progress_bar=False, normalize_embeddings=True)
    clustering = AgglomerativeClustering(
        n_clusters=None, metric='cosine', linkage='average',
        distance_threshold=shelf_cluster_threshold)
    name_cluster = clustering.fit_predict(emb)
    name_to_cluster = {nm: int(c) for nm, c in zip(unique_names, name_cluster)}
    n_clusters = len(set(name_cluster))
    print(f"  → {n_clusters} conceptos semánticos de shelf")

    # df por concepto = nº de historias distintas con un shelf de ese concepto
    concept_stories = {}
    for sidx in range(n_shelves):
        c = name_to_cluster[shelf_name_of[sidx]]
        concept_stories.setdefault(c, set()).update(shelf_members.get(sidx, ()))
    concept_idf = {c: math.log(n / (1 + len(s))) for c, s in concept_stories.items()}

    # matriz historias × shelves, peso = idf_concepto × 1/log(tamaño+1)
    si, sj, sv = [], [], []
    for sidx, members in shelf_members.items():
        concept = name_to_cluster[shelf_name_of[sidx]]
        idf = concept_idf[concept]
        size_pen = 1.0 / math.log(len(members) + 1.0 + 1.0)  # +1 extra evita log(2)→peso enorme en size=1
        w = idf * size_pen
        for h in members:
            si.append(h); sj.append(sidx); sv.append(w)
    shelf_matrix = sparse.csr_matrix((sv, (si, sj)), shape=(n, n_shelves))
    shelf_norm = normalize(shelf_matrix, norm='l2', axis=1)  # filas L2 → coseno = producto

    # ── SYNOPSIS → TF-IDF ────────────────────────────────────────────────
    synopses = [r['synopsis'] for r in rows]
    syn_vec = TfidfVectorizer(max_features=8000, stop_words='english',
                              min_df=2, max_df=0.9, sublinear_tf=True)
    syn_matrix = syn_vec.fit_transform(synopses)
    syn_norm = normalize(syn_matrix, norm='l2', axis=1)
    print(f"synopsis: {syn_matrix.shape[1]} términos")

    cache = {
        'ids': ids, 'id_to_idx': id_to_idx, 'titles': titles, 'authors': authors,
        'tag_matrix': tag_matrix.tocsr(), 'tag_count': tag_count, 'tag_list': tag_list,
        'shelf_norm': shelf_norm.tocsr(),
        'syn_norm': syn_norm.tocsr(),
    }
    with open(cache_path, 'wb') as f:
        pickle.dump(cache, f)
    print(f"\n✓ caché guardado en {cache_path}")
    return cache


# ── consulta ───────────────────────────────────────────────────────────────

def load_cache(cache_path):
    with open(cache_path, 'rb') as f:
        return pickle.load(f)


def similar(cache, story_id, k=10, w_tags=1.0, w_shelf=1.0, w_syn=1.0):
    if story_id not in cache['id_to_idx']:
        return None
    i = cache['id_to_idx'][story_id]
    n = len(cache['ids'])

    # Jaccard de tags: i vs todas
    tm = cache['tag_matrix']
    tcount = cache['tag_count']
    inter = np.asarray(tm.dot(tm[i].T).todense()).flatten()   # |A ∩ B|
    union = tcount + tcount[i] - inter
    with np.errstate(divide='ignore', invalid='ignore'):
        jac = np.where(union > 0, inter / union, 0.0)

    # coseno shelves: i vs todas (filas ya L2-normalizadas)
    sh = cache['shelf_norm']
    cos_shelf = np.asarray(sh.dot(sh[i].T).todense()).flatten()

    # coseno synopsis
    sy = cache['syn_norm']
    cos_syn = np.asarray(sy.dot(sy[i].T).todense()).flatten()

    # excluir la propia historia antes de normalizar
    jac[i] = cos_shelf[i] = cos_syn[i] = 0.0

    # normalizar cada señal a [0,1] por su máximo en esta query → pesos comparables
    def unit(v):
        m = v.max()
        return v / m if m > 0 else v
    jac_n, shelf_n, syn_n = unit(jac), unit(cos_shelf), unit(cos_syn)

    tw = w_tags + w_shelf + w_syn or 1.0
    score = (w_tags * jac_n + w_shelf * shelf_n + w_syn * syn_n) / tw
    score[i] = -1.0  # excluir la propia

    top = np.argpartition(score, -k)[-k:]
    top = top[np.argsort(score[top])[::-1]]

    ids = cache['ids']
    out = []
    for j in top:
        sid = ids[j]
        out.append({
            'id': sid, 'title': cache['titles'].get(sid, '?'),
            'author': cache['authors'].get(sid, '?'),
            'score': float(score[j]),
            'tags': float(jac[j]), 'shelf': float(cos_shelf[j]), 'syn': float(cos_syn[j]),
        })
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default=DEFAULT_DB)
    p.add_argument('--cache', default=DEFAULT_CACHE)
    p.add_argument('--build', action='store_true')
    p.add_argument('--id', type=int)
    p.add_argument('--k', type=int, default=10)
    p.add_argument('--w-tags', type=float, default=1.0)
    p.add_argument('--w-shelf', type=float, default=1.0)
    p.add_argument('--w-syn', type=float, default=1.0)
    args = p.parse_args()

    if args.build or not os.path.exists(args.cache):
        build_cache(args.db, args.cache)

    if args.id is not None:
        cache = load_cache(args.cache)
        res = similar(cache, args.id, args.k, args.w_tags, args.w_shelf, args.w_syn)
        if res is None:
            print(f"Historia {args.id} no está en el caché."); return
        base = cache['titles'].get(args.id, '?')
        print(f"\nVecinas de [{args.id}] {base}\n")
        print(f"{'ID':>6}  {'Score':>6}  {'tags':>5}  {'shelf':>5}  {'syn':>5}  Título")
        print("─" * 78)
        for r in res:
            print(f"{r['id']:6d}  {r['score']:.4f}  {r['tags']:.3f}  {r['shelf']:.3f}  "
                  f"{r['syn']:.3f}  {r['title'][:38]}")


if __name__ == '__main__':
    main()
