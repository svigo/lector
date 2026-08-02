#!/usr/bin/env python3
"""
Refinamiento interactivo de clusters.
Uso: python3 refine.py clasificacion.csv

Comandos:
  show              - muestra todos los clusters con keywords y tamaños
  view N            - muestra hasta 25 archivos del cluster N
  merge A B         - fusiona el cluster B dentro de A
  split N K         - divide el cluster N en K sub-clusters
  rename N nombre   - renombra el cluster N
  save              - guarda el CSV actualizado
  quit              - salir (pide confirmación si hay cambios sin guardar)
"""
import sys, pickle
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer
from sklearn.pipeline import make_pipeline

try:
    import readline  # habilita historial con flechas arriba/abajo
except ImportError:
    pass


def top_keywords(vec, X, idx_list, n=10):
    mask = np.zeros(X.shape[0], dtype=bool)
    mask[idx_list] = True
    center = np.asarray(X[mask].mean(axis=0)).flatten()
    top = center.argsort()[-n:][::-1]
    return [vec.get_feature_names_out()[i] for i in top]


def show_clusters(df, vec, X, name_to_idx):
    clusters = sorted(df['cluster'].unique())
    print(f"\n{'ID':>4}  {'Nombre':<22}  {'Docs':>6}  Palabras clave")
    print("─" * 75)
    for c in clusters:
        mask_df = df['cluster'] == c
        cname = df.loc[mask_df, 'cluster_name'].iloc[0]
        size = int(mask_df.sum())
        idx_list = [name_to_idx[n] for n in df.loc[mask_df, 'archivo'] if n in name_to_idx]
        if idx_list:
            kw = top_keywords(vec, X, idx_list, n=5)
        else:
            kw = df.loc[mask_df, 'cluster_keywords'].iloc[0].split(', ')[:5]
        print(f"  {c:3d}  {cname:<22}  {size:6d}  [{', '.join(kw)}]")
    print()


def recalc_keywords(df, vec, X, name_to_idx, cluster_id):
    mask_df = df['cluster'] == cluster_id
    idx_list = [name_to_idx[n] for n in df.loc[mask_df, 'archivo'] if n in name_to_idx]
    if not idx_list:
        return
    kw = ', '.join(top_keywords(vec, X, idx_list))
    df.loc[mask_df, 'cluster_keywords'] = kw


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 refine.py clasificacion.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    pkl_path = csv_path.replace('.csv', '.pkl')

    print(f"Cargando {csv_path}...")
    df = pd.read_csv(csv_path)
    if 'cluster_name' not in df.columns:
        df['cluster_name'] = df['cluster'].astype(str)
    else:
        df['cluster_name'] = df['cluster_name'].astype(str)

    print(f"Cargando vectorización ({pkl_path})...")
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    vec = data['vectorizer']
    X = data['X']
    names_list = data['names']
    name_to_idx = {n: i for i, n in enumerate(names_list)}

    next_id = int(df['cluster'].max()) + 1
    unsaved = False

    print(f"  {len(df)} documentos, {df['cluster'].nunique()} clusters")
    show_clusters(df, vec, X, name_to_idx)
    print("Comandos: show | view N | merge A B | split N K | rename N nombre | save | quit | help\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        # ── show ──────────────────────────────────────────────────────────
        if cmd in ('show', 's'):
            show_clusters(df, vec, X, name_to_idx)

        # ── view N ────────────────────────────────────────────────────────
        elif cmd in ('view', 'v') and len(parts) >= 2:
            try:
                c = int(parts[1])
            except ValueError:
                print("  Uso: view N"); continue
            files = df[df['cluster'] == c]['archivo'].tolist()
            if not files:
                print(f"  Cluster {c} no existe."); continue
            print(f"\nCluster {c} — {len(files)} archivos:")
            for fn in files[:25]:
                print(f"  {fn}")
            if len(files) > 25:
                print(f"  ... y {len(files) - 25} más")
            print()

        # ── merge A B ─────────────────────────────────────────────────────
        elif cmd in ('merge', 'm') and len(parts) >= 3:
            try:
                a, b = int(parts[1]), int(parts[2])
            except ValueError:
                print("  Uso: merge A B"); continue
            if a == b:
                print("  A y B son el mismo cluster."); continue
            existing = df['cluster'].unique()
            if a not in existing or b not in existing:
                print("  Uno o ambos clusters no existen."); continue
            count_b = int((df['cluster'] == b).sum())
            name_a = df.loc[df['cluster'] == a, 'cluster_name'].iloc[0]
            df.loc[df['cluster'] == b, 'cluster'] = a
            df.loc[df['cluster'] == a, 'cluster_name'] = name_a
            recalc_keywords(df, vec, X, name_to_idx, a)
            print(f"  ✓ Cluster {b} ({count_b} docs) fusionado en {a}.")
            unsaved = True

        # ── split N K ─────────────────────────────────────────────────────
        elif cmd in ('split', 'sp') and len(parts) >= 3:
            try:
                c, k = int(parts[1]), int(parts[2])
            except ValueError:
                print("  Uso: split N K"); continue
            if c not in df['cluster'].values:
                print(f"  Cluster {c} no existe."); continue
            if k < 2:
                print("  K debe ser >= 2."); continue
            mask_df = df['cluster'] == c
            files_in_c = df.loc[mask_df, 'archivo'].tolist()
            idx_list = [name_to_idx[n] for n in files_in_c if n in name_to_idx]
            if len(idx_list) < k:
                print(f"  Solo {len(idx_list)} docs, no se puede dividir en {k}."); continue

            X_sub = X[idx_list]
            n_comp = min(50, X_sub.shape[1] - 1, X_sub.shape[0] - 1)
            lsa = make_pipeline(TruncatedSVD(n_components=n_comp, random_state=42),
                                 Normalizer(copy=False))
            X_sub_lsa = lsa.fit_transform(X_sub)
            sub_labels = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=5).fit_predict(X_sub_lsa)

            new_ids = list(range(next_id, next_id + k))
            next_id += k
            base_name = df.loc[mask_df, 'cluster_name'].iloc[0]

            for j, fname in enumerate(files_in_c):
                new_c = new_ids[sub_labels[j]]
                df.loc[df['archivo'] == fname, 'cluster'] = new_c
                df.loc[df['archivo'] == fname, 'cluster_name'] = f"{base_name}.{sub_labels[j]}"

            for new_c in new_ids:
                recalc_keywords(df, vec, X, name_to_idx, new_c)

            print(f"  ✓ Cluster {c} dividido en {k} sub-clusters: {new_ids}")
            unsaved = True

        # ── rename N nombre ───────────────────────────────────────────────
        elif cmd in ('rename', 'r') and len(parts) >= 3:
            try:
                c = int(parts[1])
            except ValueError:
                print("  Uso: rename N nombre"); continue
            name = ' '.join(parts[2:])
            if c not in df['cluster'].values:
                print(f"  Cluster {c} no existe."); continue
            df.loc[df['cluster'] == c, 'cluster_name'] = name
            print(f"  ✓ Cluster {c} → '{name}'")
            unsaved = True

        # ── save ──────────────────────────────────────────────────────────
        elif cmd == 'save':
            df.sort_values(['cluster', 'archivo']).to_csv(csv_path, index=False)
            print(f"  ✓ Guardado en {csv_path}")
            unsaved = False

        # ── quit ──────────────────────────────────────────────────────────
        elif cmd in ('quit', 'q', 'exit'):
            if unsaved:
                resp = input("  Cambios sin guardar. ¿Guardar? [s/n]: ").strip().lower()
                if resp in ('s', 'si', 'y', 'yes'):
                    df.sort_values(['cluster', 'archivo']).to_csv(csv_path, index=False)
                    print(f"  ✓ Guardado en {csv_path}")
            break

        # ── help ──────────────────────────────────────────────────────────
        elif cmd == 'help':
            print(__doc__)

        else:
            print("  Comandos: show | view N | merge A B | split N K | rename N nombre | save | quit")


if __name__ == '__main__':
    main()
