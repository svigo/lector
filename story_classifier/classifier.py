#!/usr/bin/env python3
"""
Clasificador temático de historias.
Uso: python3 classifier.py /ruta/historias/ [--min-k 5] [--max-k 30] [--output clasificacion.csv] [--stopwords archivo.txt] [--synopsis]
Genera: clasificacion.csv + clasificacion.pkl (necesario para refine.py)
"""
import os, sys, glob, argparse, pickle
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer
from sklearn.pipeline import make_pipeline


def read_files(folder, synopsis_only=False):
    paths = sorted(glob.glob(os.path.join(folder, '**', '*.txt'), recursive=True))
    texts, names = [], []
    for path in paths:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                if synopsis_only:
                    text = ''
                    for line in f:
                        if line.startswith('Synopsis:'):
                            text = line.split(':', 1)[1].strip()
                            break
                        if line.startswith('---'):
                            break
                else:
                    text = f.read().strip()
            if text:
                texts.append(text)
                names.append(os.path.relpath(path, folder))
        except Exception as e:
            print(f"  Advertencia: {path}: {e}", file=sys.stderr)
    return names, texts


def find_optimal_k(X, k_range):
    inertias = []
    print(f"Probando K {k_range[0]}–{k_range[-1]}...")
    for k in k_range:
        km = MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=1000, n_init=3)
        km.fit(X)
        inertias.append(km.inertia_)
        print(f"  K={k:3d}  inercia={km.inertia_:,.0f}")

    arr = np.array(inertias)
    r = arr.max() - arr.min()
    norm = (arr - arr.min()) / (r if r > 0 else 1)
    d2 = np.diff(np.diff(norm))
    return k_range[int(np.argmax(d2)) + 1]


def top_keywords(vec, X, mask, n=10):
    center = np.asarray(X[mask].mean(axis=0)).flatten()
    idx = center.argsort()[-n:][::-1]
    return [vec.get_feature_names_out()[i] for i in idx]


def main():
    p = argparse.ArgumentParser(description='Clasificador temático de historias')
    p.add_argument('folder', nargs='?', default=os.path.expanduser('~/corpus-historias/stories/resto'),
                   help='Carpeta con archivos .txt')
    p.add_argument('--min-k', type=int, default=5)
    p.add_argument('--max-k', type=int, default=30)
    p.add_argument('--output', default=os.path.expanduser('~/corpus-historias/clasificacion.csv'))
    p.add_argument('--stopwords', help='Archivo con stopwords extra (una por línea, # para comentarios)')
    p.add_argument('--synopsis', action='store_true', help='Clasificar por sinopsis del header en vez del texto completo')
    args = p.parse_args()

    mode = "sinopsis" if args.synopsis else "texto completo"
    print(f"Leyendo archivos de {args.folder} [{mode}]...")
    names, texts = read_files(args.folder, synopsis_only=args.synopsis)
    print(f"  {len(texts)} archivos cargados.")
    if len(texts) < args.min_k:
        sys.exit(f"Error: menos archivos ({len(texts)}) que el mínimo de clusters ({args.min_k}).")

    extra_stopwords = []
    if args.stopwords:
        with open(args.stopwords, 'r', encoding='utf-8') as f:
            extra_stopwords = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        print(f"  {len(extra_stopwords)} stopwords extra cargadas de {args.stopwords}")

    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    stop_words = list(ENGLISH_STOP_WORDS) + extra_stopwords

    print("Vectorizando con TF-IDF...")
    vec = TfidfVectorizer(max_features=10000, stop_words=stop_words,
                          min_df=2, max_df=0.95, sublinear_tf=True)
    X = vec.fit_transform(texts)
    print(f"  {X.shape[1]} términos, {X.shape[0]} documentos")

    print("Reduciendo dimensionalidad (LSA)...")
    n_comp = min(200, X.shape[1] - 1, X.shape[0] - 1)
    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    lsa = make_pipeline(svd, Normalizer(copy=False))
    X_lsa = lsa.fit_transform(X)
    print(f"  {n_comp} componentes, varianza explicada: {svd.explained_variance_ratio_.sum():.1%}")

    step = max(1, (args.max_k - args.min_k) // 10)
    k_range = sorted(set(range(args.min_k, args.max_k + 1, step)) | {args.max_k})
    optimal_k = find_optimal_k(X_lsa, k_range)
    print(f"\n→ K óptimo detectado: {optimal_k} clusters")

    print(f"Clustering final con K={optimal_k}...")
    km = MiniBatchKMeans(n_clusters=optimal_k, random_state=42, batch_size=1000, n_init=5)
    labels = km.fit_predict(X_lsa).tolist()

    name_to_idx = {n: i for i, n in enumerate(names)}
    kw = {}
    for c in sorted(set(labels)):
        mask = np.zeros(X.shape[0], dtype=bool)
        for i, l in enumerate(labels):
            if l == c:
                mask[i] = True
        kw[c] = top_keywords(vec, X, mask)

    df = pd.DataFrame({
        'archivo': names,
        'cluster': labels,
        'cluster_name': [str(c) for c in labels],
        'cluster_keywords': [', '.join(kw[l]) for l in labels],
    }).sort_values(['cluster', 'archivo'])
    df.to_csv(args.output, index=False)

    pkl_path = args.output.replace('.csv', '.pkl')
    with open(pkl_path, 'wb') as f:
        pickle.dump({'vectorizer': vec, 'X': X, 'names': names}, f)

    print(f"\nGuardado: {args.output}")
    print(f"Datos para refinado: {pkl_path}")
    print("\n=== CLUSTERS ===")
    sizes = {c: labels.count(c) for c in sorted(set(labels))}
    for c in sorted(sizes):
        print(f"  {c:3d}: {sizes[c]:5d} docs — [{', '.join(kw[c][:5])}]")
    print(f"\nPara refinar: python3 refine.py {args.output}")


if __name__ == '__main__':
    main()
