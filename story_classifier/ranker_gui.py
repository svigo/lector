#!/usr/bin/env python3
"""
GUI de calibración del ranking de historias.
Uso: python3 ranker_gui.py [--db stories.db] [--stories-dir stories/resto]
"""

import tkinter as tk
from tkinter import ttk
import argparse
import math
import re
import sqlite3
import subprocess
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from ranker import rank_stories, percentile_rank
import similarity


SIGNALS = [
    ('bayesian',   'Valoración  (Bayesian, penaliza pocos votos)'),
    ('engagement', 'Enganche  (% de lectores que votaron)'),
    ('shelves',    'Colecciones  (en cuántas listas aparece)'),
    ('quality',    'Calidad  (listas con nombre positivo)'),
    ('longevity',  'Longevidad  (lectores/año, clásico vs nuevo)'),
    ('length',     'Longitud  (palabras totales, dedicación del autor)'),
    ('vocab',      'Vocabulario  (diversidad léxica, índice de Guiraud)'),
]


def open_story(story_id, db_path, stories_dir):
    conn = sqlite3.connect(db_path)
    row = conn.execute('SELECT filename FROM stories WHERE id=?', (story_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return
    filepath = os.path.join(stories_dir, row[0])
    if not os.path.exists(filepath):
        return
    lector = os.path.expanduser('~/proyectos/lector')
    subprocess.Popen([f'{lector}/.venv/bin/python', f'{lector}/main.py', filepath])


def build_gui(db_path, stories_dir, cache_path):
    root = tk.Tk()
    root.title("Calibrador de Ranking")
    sim_cache = {'data': None}  # se carga lazy al pedir similares
    root.resizable(True, True)

    # ── Sliders ──────────────────────────────────────────────────────────
    sliders_frame = ttk.LabelFrame(root, text="Pesos", padding=(12, 6))
    sliders_frame.pack(fill='x', padx=12, pady=(10, 4))

    weight_vars = {}
    for i, (key, label) in enumerate(SIGNALS):
        var = tk.DoubleVar(value=1.0)
        weight_vars[key] = var

        ttk.Label(sliders_frame, text=label, width=32, anchor='w').grid(
            row=i, column=0, padx=(0, 8), pady=4, sticky='w')

        slider = ttk.Scale(sliders_frame, from_=0.0, to=3.0,
                           variable=var, orient='horizontal', length=280)
        slider.grid(row=i, column=1, padx=4, pady=4)

        val_lbl = ttk.Label(sliders_frame, text="1.00", width=5, anchor='e')
        val_lbl.grid(row=i, column=2, padx=(4, 0))

        slider.configure(
            command=lambda v, lbl=val_lbl: lbl.config(text=f"{float(v):.2f}")
        )

    # ── Controles ────────────────────────────────────────────────────────
    ctrl_frame = ttk.Frame(root)
    ctrl_frame.pack(fill='x', padx=12, pady=4)

    ttk.Label(ctrl_frame, text="Mostrar top N:").pack(side='left')
    top_var = tk.IntVar(value=50)
    ttk.Spinbox(ctrl_frame, from_=5, to=500, textvariable=top_var,
                width=6).pack(side='left', padx=(4, 16))

    ttk.Label(ctrl_frame, text="Filtrar palabras:").pack(side='left')
    filter_var = tk.StringVar(value="")
    ttk.Entry(ctrl_frame, textvariable=filter_var, width=24).pack(side='left', padx=(4, 16))

    status_var = tk.StringVar(value="")
    btn = ttk.Button(ctrl_frame, text="▶  Calcular",
                     command=lambda: run_ranking())
    btn.pack(side='left')

    btn_sim = ttk.Button(ctrl_frame, text="≈ Ver similares",
                         command=lambda: open_similar(selected_sid()))
    btn_sim.pack(side='left', padx=(8, 0))

    btn_freq = ttk.Button(ctrl_frame, text="# Por frecuencia",
                          command=lambda: run_frequency())
    btn_freq.pack(side='left', padx=(8, 0))

    btn_central = ttk.Button(ctrl_frame, text="★ Centralidad",
                             command=lambda: open_centrality())
    btn_central.pack(side='left', padx=(8, 0))

    ttk.Label(ctrl_frame, textvariable=status_var,
              foreground='#555').pack(side='left', padx=12)

    # ── Tabla de resultados ───────────────────────────────────────────────
    table_frame = ttk.LabelFrame(root, text="Resultados  (doble clic para leer)", padding=(6, 4))
    table_frame.pack(fill='both', expand=True, padx=12, pady=(4, 10))

    cols = ('rank', 'score', 'rating', 'eng', 'shelves', 'qual', 'title', 'author')
    headers = {
        'rank': '#', 'score': 'Puntaje', 'rating': 'Valoración',
        'eng': 'Enganche‰', 'shelves': 'Listas', 'qual': 'Calidad',
        'title': 'Título', 'author': 'Autor',
    }
    widths = {
        'rank': 40, 'score': 72, 'rating': 60, 'eng': 55,
        'shelves': 60, 'qual': 45, 'title': 340, 'author': 160,
    }

    tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=22)
    for col in cols:
        anchor = 'w' if col in ('title', 'author') else 'center'
        tree.heading(col, text=headers[col],
                     command=lambda c=col: sort_tree(tree, c, False))
        tree.column(col, width=widths[col], anchor=anchor, stretch=(col == 'title'))

    vsb = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side='left', fill='both', expand=True)
    vsb.pack(side='right', fill='y')

    tree.tag_configure('odd', background='#f5f5f5')

    # story_id por iid del item
    iid_to_sid = {}
    text_cache = {}  # filename -> contenido en minúsculas, cacheado por sesión

    def get_filtered_ids(words):
        """IDs de historias donde TODAS las palabras aparecen en título,
        sinopsis, tags o texto completo del archivo (AND)."""
        conn = sqlite3.connect(db_path)
        rows = conn.execute('''
            SELECT s.id, s.filename, s.title, s.synopsis,
                   COALESCE(GROUP_CONCAT(DISTINCT t.tag), '') AS tags,
                   COALESCE(GROUP_CONCAT(DISTINCT ut.name), '') AS user_tags
            FROM stories s
            LEFT JOIN tags t ON t.story_id = s.id
            LEFT JOIN story_user_tags sut ON sut.story_id = s.id
            LEFT JOIN user_tags ut ON ut.id = sut.tag_id
            WHERE s.scraped_at IS NOT NULL AND s.scraped_at != 'NOT_FOUND'
            GROUP BY s.id
        ''').fetchall()
        conn.close()

        matched = []
        total = len(rows)
        for i, (sid, filename, title, synopsis, tags, user_tags) in enumerate(rows):
            meta = ' '.join(filter(None, [title, synopsis, tags, user_tags])).lower()
            ok = True
            for w in words:
                if w in meta:
                    continue
                content = text_cache.get(filename)
                if content is None:
                    filepath = os.path.join(stories_dir, filename or '')
                    try:
                        with open(filepath, encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                    except OSError:
                        content = ''
                    text_cache[filename] = content
                if w not in content:
                    ok = False
                    break
            if ok:
                matched.append(sid)
            if i % 500 == 0:
                status_var.set(f"Filtrando... {i}/{total}")
                root.update()
        return matched

    def run_ranking():
        weights = {k: v.get() for k, v in weight_vars.items()}
        status_var.set("Calculando...")
        btn.state(['disabled'])
        root.update()
        try:
            words = [w.lower() for w in filter_var.get().split() if w]
            allowed_ids = get_filtered_ids(words) if words else None
            results = rank_stories(db_path, weights, top_var.get(), allowed_ids)
            for item in tree.get_children():
                tree.delete(item)
            iid_to_sid.clear()
            for s in results:
                tag = 'odd' if s['rank'] % 2 else ''
                iid = tree.insert('', 'end', tags=(tag,), values=(
                    s['rank'],
                    f"{s['score']:.4f}",
                    f"{s['bayesian']:.2f}",
                    f"{s['engagement']:.2f}",
                    s['shelves'],
                    s['quality'],
                    s['title'],
                    s['author'],
                ))
                iid_to_sid[iid] = s['id']
            status_var.set(f"{len(results)} historias  |  doble clic para abrir")
        except Exception as e:
            status_var.set(f"Error: {e}")
        finally:
            btn.state(['!disabled'])

    def run_frequency():
        words = filter_var.get().split()
        if not words:
            status_var.set("Escribí una palabra en el filtro")
            return
        word = words[0].lower()
        pattern = re.compile(r'\b' + re.escape(word) + r'\b')

        status_var.set("Contando ocurrencias...")
        btn_freq.state(['disabled'])
        root.update()
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute('SELECT id, filename, title, author FROM stories').fetchall()
            conn.close()

            counted = []
            total = len(rows)
            for i, (sid, filename, title, author) in enumerate(rows):
                content = text_cache.get(filename)
                if content is None:
                    filepath = os.path.join(stories_dir, filename or '')
                    try:
                        with open(filepath, encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                    except OSError:
                        content = ''
                    text_cache[filename] = content
                count = len(pattern.findall(content))
                if count > 0:
                    counted.append((sid, title or '?', author or '?', count))
                if i % 500 == 0:
                    status_var.set(f"Contando... {i}/{total}")
                    root.update()

            counted.sort(key=lambda x: x[3], reverse=True)
            counted = counted[:top_var.get()]

            for item in tree.get_children():
                tree.delete(item)
            iid_to_sid.clear()
            for rank, (sid, title, author, count) in enumerate(counted, start=1):
                tag = 'odd' if rank % 2 else ''
                iid = tree.insert('', 'end', tags=(tag,), values=(
                    rank, count, '', '', '', '', title, author,
                ))
                iid_to_sid[iid] = sid
            status_var.set(f'{len(counted)} historias con "{word}"  |  ordenadas por frecuencia')
        except Exception as e:
            status_var.set(f"Error: {e}")
        finally:
            btn_freq.state(['!disabled'])

    def dispersion_entropy(positions, text_len, bins=10):
        """0 = todas las apariciones agrupadas en un mismo tramo, 1 = repartidas
        parejo a lo largo de todo el texto."""
        if len(positions) <= 1 or text_len == 0:
            return 0.0
        counts = [0] * bins
        for p in positions:
            b = min(int(p / text_len * bins), bins - 1)
            counts[b] += 1
        n = len(positions)
        probs = [c / n for c in counts if c > 0]
        if len(probs) <= 1:
            return 0.0
        entropy = -sum(p * math.log(p) for p in probs)
        max_entropy = math.log(min(bins, n))
        return entropy / max_entropy if max_entropy > 0 else 0.0

    # ── Ventana de centralidad de una palabra ───────────────────────────────
    def open_centrality():
        words = filter_var.get().split()
        if not words:
            status_var.set("Escribí una palabra en el filtro")
            return
        word = words[0].lower()
        pattern = re.compile(r'\b' + re.escape(word) + r'\b')

        win = tk.Toplevel(root)
        win.title(f"Centralidad de: {word}")
        win.geometry("760x560")

        cframe = ttk.LabelFrame(win, text="Pesos", padding=(10, 4))
        cframe.pack(fill='x', padx=10, pady=(10, 4))
        c_signals = [('density',    'Densidad  (apariciones / palabras totales)'),
                     ('dispersion', 'Dispersión  (repartida vs. concentrada)'),
                     ('synopsis',   'Sinopsis/tags  (mencionada en el resumen)')]
        c_vars = {}
        for r, (key, label) in enumerate(c_signals):
            v = tk.DoubleVar(value=1.0)
            c_vars[key] = v
            ttk.Label(cframe, text=label, width=34, anchor='w').grid(row=r, column=0, pady=3, sticky='w')
            sc = ttk.Scale(cframe, from_=0.0, to=3.0, variable=v, orient='horizontal', length=240)
            sc.grid(row=r, column=1, padx=4)
            vl = ttk.Label(cframe, text="1.00", width=5)
            vl.grid(row=r, column=2)
            sc.configure(command=lambda val, lbl=vl: lbl.config(text=f"{float(val):.2f}"))

        cstatus_var = tk.StringVar(value="")
        ttk.Button(cframe, text="↻ Recalcular", command=lambda: refresh_centrality()).grid(
            row=0, column=3, rowspan=3, padx=10)
        ttk.Label(win, textvariable=cstatus_var, foreground='#555').pack(anchor='w', padx=12)

        cols = ('rank', 'score', 'count', 'density', 'disp', 'title', 'author')
        hd = {'rank': '#', 'score': 'Score', 'count': 'Apar.', 'density': 'Densid.',
              'disp': 'Disper.', 'title': 'Título', 'author': 'Autor'}
        wd = {'rank': 40, 'score': 65, 'count': 50, 'density': 65, 'disp': 65,
              'title': 320, 'author': 160}
        ctree = ttk.Treeview(win, columns=cols, show='headings', height=20)
        for c in cols:
            ctree.heading(c, text=hd[c])
            ctree.column(c, width=wd[c], anchor='w' if c in ('title', 'author') else 'center',
                        stretch=(c == 'title'))
        ctree.pack(fill='both', expand=True, padx=10, pady=8)
        c_iid_to_sid = {}
        raw_cache = {'data': None}  # (ids, titles, authors, count, density, dispersion, synopsis)

        def scan():
            conn = sqlite3.connect(db_path)
            rows = conn.execute('''
                SELECT s.id, s.filename, s.title, s.author, s.synopsis, s.word_count,
                       COALESCE(GROUP_CONCAT(DISTINCT t.tag), '') AS tags,
                       COALESCE(GROUP_CONCAT(DISTINCT ut.name), '') AS user_tags
                FROM stories s
                LEFT JOIN tags t ON t.story_id = s.id
                LEFT JOIN story_user_tags sut ON sut.story_id = s.id
                LEFT JOIN user_tags ut ON ut.id = sut.tag_id
                WHERE s.scraped_at IS NOT NULL AND s.scraped_at != 'NOT_FOUND'
                GROUP BY s.id
            ''').fetchall()
            conn.close()

            ids, titles, authors = [], [], []
            raw = {k: [] for k in ('count', 'density', 'dispersion', 'synopsis')}
            total = len(rows)
            for i, (sid, filename, title, author, synopsis, word_count, tags, user_tags) in enumerate(rows):
                content = text_cache.get(filename)
                if content is None:
                    filepath = os.path.join(stories_dir, filename or '')
                    try:
                        with open(filepath, encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                    except OSError:
                        content = ''
                    text_cache[filename] = content

                matches = list(pattern.finditer(content))
                count = len(matches)
                if count == 0:
                    if i % 500 == 0:
                        cstatus_var.set(f"Escaneando... {i}/{total}")
                        win.update()
                    continue

                positions = [m.start() for m in matches]
                wc = word_count or max(len(content.split()), 1)
                meta = ' '.join(filter(None, [title, synopsis, tags, user_tags])).lower()

                ids.append(sid)
                titles.append(title or '?')
                authors.append(author or '?')
                raw['count'].append(count)
                raw['density'].append(count / wc)
                raw['dispersion'].append(dispersion_entropy(positions, len(content)))
                raw['synopsis'].append(1.0 if pattern.search(meta) else 0.0)

                if i % 500 == 0:
                    cstatus_var.set(f"Escaneando... {i}/{total}")
                    win.update()

            return ids, titles, authors, raw

        def refresh_centrality():
            cstatus_var.set("Calculando...")
            win.update()
            try:
                if raw_cache['data'] is None:
                    raw_cache['data'] = scan()
                ids, titles, authors, raw = raw_cache['data']

                if not ids:
                    for it in ctree.get_children():
                        ctree.delete(it)
                    cstatus_var.set(f'Ninguna historia contiene "{word}"')
                    return

                w = {k: v.get() for k, v in c_vars.items()}
                norm = {
                    'density':    percentile_rank(raw['density']),
                    'dispersion': percentile_rank(raw['dispersion']),
                    'synopsis':   raw['synopsis'],  # ya está en [0,1]
                }
                total_w = sum(w.values()) or 1
                scored = []
                for i in range(len(ids)):
                    score = (w['density'] * norm['density'][i]
                             + w['dispersion'] * norm['dispersion'][i]
                             + w['synopsis'] * norm['synopsis'][i]) / total_w
                    scored.append((score, ids[i], titles[i], authors[i],
                                   raw['count'][i], raw['density'][i], raw['dispersion'][i]))
                scored.sort(key=lambda x: x[0], reverse=True)
                scored = scored[:top_var.get()]

                for it in ctree.get_children():
                    ctree.delete(it)
                c_iid_to_sid.clear()
                for rank, (score, sid, title, author, count, density, disp) in enumerate(scored, start=1):
                    iid = ctree.insert('', 'end', values=(
                        rank, f"{score:.3f}", count, f"{density:.4f}", f"{disp:.2f}", title, author,
                    ))
                    c_iid_to_sid[iid] = sid
                cstatus_var.set(f'{len(ids)} historias con "{word}"  |  doble clic para abrir')
            except Exception as e:
                cstatus_var.set(f"Error: {e}")

        def c_double(e):
            sel = ctree.selection()
            if sel:
                open_story(c_iid_to_sid.get(sel[0]), db_path, stories_dir)
        ctree.bind('<Double-1>', c_double)

        refresh_centrality()

    def selected_sid():
        sel = tree.selection()
        return iid_to_sid.get(sel[0]) if sel else None

    def on_double_click(event):
        sid = selected_sid()
        if sid:
            open_story(sid, db_path, stories_dir)

    tree.bind('<Double-1>', on_double_click)

    # ── Ventana de historias similares ────────────────────────────────────
    def open_similar(sid):
        if sid is None:
            status_var.set("Seleccioná una historia primero")
            return
        # cargar caché lazy (puede tardar la primera vez)
        if sim_cache['data'] is None:
            if not os.path.exists(cache_path):
                status_var.set(f"Falta el caché: corré  python3 similarity.py --build")
                return
            status_var.set("Cargando caché de similitud...")
            root.update()
            sim_cache['data'] = similarity.load_cache(cache_path)
            status_var.set("")

        cache = sim_cache['data']
        if sid not in cache['id_to_idx']:
            status_var.set(f"La historia {sid} no está en el caché de similitud")
            return

        win = tk.Toplevel(root)
        win.title(f"Similares a: {cache['titles'].get(sid, sid)}")
        win.geometry("760x560")

        head = ttk.Label(win, text=f"[{sid}] {cache['titles'].get(sid,'?')} — {cache['authors'].get(sid,'')}",
                         font=('', 10, 'bold'))
        head.pack(anchor='w', padx=10, pady=(10, 4))

        sframe = ttk.LabelFrame(win, text="Pesos de similitud", padding=(10, 4))
        sframe.pack(fill='x', padx=10)
        sim_signals = [('tags', 'Tags (Jaccard)'),
                       ('shelf', 'Colecciones (lectores)'),
                       ('syn', 'Sinopsis (texto)')]
        sim_vars = {}
        for r, (key, label) in enumerate(sim_signals):
            v = tk.DoubleVar(value=1.0)
            sim_vars[key] = v
            ttk.Label(sframe, text=label, width=22, anchor='w').grid(row=r, column=0, pady=3, sticky='w')
            sc = ttk.Scale(sframe, from_=0.0, to=3.0, variable=v, orient='horizontal', length=240)
            sc.grid(row=r, column=1, padx=4)
            vl = ttk.Label(sframe, text="1.00", width=5)
            vl.grid(row=r, column=2)
            sc.configure(command=lambda val, lbl=vl: lbl.config(text=f"{float(val):.2f}"))

        ttk.Button(sframe, text="↻ Recalcular", command=lambda: refresh_sim()).grid(
            row=0, column=3, rowspan=3, padx=10)

        cols = ('id', 'score', 'tags', 'shelf', 'syn', 'title', 'author')
        hd = {'id': 'ID', 'score': 'Score', 'tags': 'Tags', 'shelf': 'Colec.',
              'syn': 'Sinop.', 'title': 'Título', 'author': 'Autor'}
        wd = {'id': 55, 'score': 60, 'tags': 55, 'shelf': 55, 'syn': 55, 'title': 270, 'author': 140}
        stree = ttk.Treeview(win, columns=cols, show='headings', height=16)
        for c in cols:
            stree.heading(c, text=hd[c])
            stree.column(c, width=wd[c], anchor='w' if c in ('title', 'author') else 'center',
                         stretch=(c == 'title'))
        stree.pack(fill='both', expand=True, padx=10, pady=8)
        sim_iid_to_sid = {}

        def refresh_sim():
            w = {k: v.get() for k, v in sim_vars.items()}
            res = similarity.similar(cache, sid, k=25,
                                     w_tags=w['tags'], w_shelf=w['shelf'], w_syn=w['syn'])
            for it in stree.get_children():
                stree.delete(it)
            sim_iid_to_sid.clear()
            for x in res:
                iid = stree.insert('', 'end', values=(
                    x['id'], f"{x['score']:.3f}", f"{x['tags']:.2f}",
                    f"{x['shelf']:.2f}", f"{x['syn']:.2f}", x['title'], x['author']))
                sim_iid_to_sid[iid] = x['id']

        def sim_double(e):
            s = stree.selection()
            if s:
                open_story(sim_iid_to_sid.get(s[0]), db_path, stories_dir)
        stree.bind('<Double-1>', sim_double)

        refresh_sim()

    def sort_tree(tv, col, reverse):
        data = [(tv.set(k, col), k) for k in tv.get_children('')]
        try:
            data.sort(key=lambda x: float(x[0]), reverse=reverse)
        except ValueError:
            data.sort(key=lambda x: x[0].lower(), reverse=reverse)
        for i, (_, k) in enumerate(data):
            tv.move(k, '', i)
            tv.item(k, tags=('odd' if i % 2 else '',))
        tv.heading(col, command=lambda: sort_tree(tv, col, not reverse))

    run_ranking()
    root.mainloop()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default=os.path.expanduser('~/corpus-historias/stories.db'))
    p.add_argument('--stories-dir', default=os.path.expanduser('~/corpus-historias/stories/resto'),
                   help='Carpeta con los archivos .txt')
    p.add_argument('--cache', default=os.path.expanduser('~/corpus-historias/similarity_cache.pkl'),
                   help='Caché de similitud (similarity.py --build)')
    args = p.parse_args()
    build_gui(args.db, args.stories_dir, args.cache)


if __name__ == '__main__':
    main()
