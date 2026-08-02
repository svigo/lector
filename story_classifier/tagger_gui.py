#!/usr/bin/env python3
"""
Sistema de tags personalizados para historias.
Uso: python3 tagger_gui.py [--db stories.db] [--stories-dir stories/resto]
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3, re, os, glob, threading, json
from datetime import datetime
import argparse
import snowballstemmer

_stemmer = snowballstemmer.stemmer('english')

def stem_terms(terms):
    return [_stemmer.stemWord(t.strip().lower()) for t in terms if t.strip()]

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS story_user_tags (
    story_id INTEGER NOT NULL,
    tag_id   INTEGER NOT NULL REFERENCES user_tags(id) ON DELETE CASCADE,
    source   TEXT DEFAULT 'manual',
    score    REAL,
    PRIMARY KEY (story_id, tag_id)
);
CREATE TABLE IF NOT EXISTS user_tag_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id      INTEGER REFERENCES user_tags(id) ON DELETE CASCADE,
    terms       TEXT,
    threshold   INTEGER,
    applied_at  TEXT,
    match_count INTEGER
);
CREATE TABLE IF NOT EXISTS story_similarities (
    story_a INTEGER NOT NULL,
    story_b INTEGER NOT NULL,
    source  TEXT DEFAULT 'user',
    PRIMARY KEY (story_a, story_b),
    CHECK (story_a < story_b)
);
"""

SEP = re.compile(r'-{10,}')
WORD_RE = re.compile(r'[a-z]+')


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


def scan_with_index(index_path, terms, threshold):
    """Query instantánea usando el índice invertido word_index.db (con stemming)."""
    terms = list(set(stem_terms(terms)))  # stemear y deduplicar
    if not terms:
        return []
    conn = sqlite3.connect(index_path)
    placeholders = ','.join('?' * len(terms))
    rows = conn.execute(f'''
        SELECT story_id, SUM(count) AS total
        FROM word_index
        WHERE word IN ({placeholders})
        GROUP BY story_id
        HAVING total >= ?
    ''', terms + [threshold]).fetchall()
    conn.close()
    return [(sid, total) for sid, total in rows]


def scan_by_disk(stories_dir, terms, threshold, progress_cb=None):
    """Fallback: relee cada archivo del disco (lento, con stemming). Usado si no hay índice."""
    term_set = set(stem_terms(terms))
    if not term_set:
        return []
    paths = sorted(glob.glob(os.path.join(stories_dir, '**', '*.txt'), recursive=True))
    results = []
    for i, path in enumerate(paths):
        if progress_cb and i % 200 == 0:
            progress_cb(i, len(paths))
        sid = story_id_from_file(path)
        if sid is None:
            continue
        body = story_body(path)
        count = sum(1 for w in WORD_RE.findall(body) if _stemmer.stemWord(w) in term_set)
        if count >= threshold:
            results.append((sid, count))
    if progress_cb:
        progress_cb(len(paths), len(paths))
    return results


def scan_stories(stories_dir, terms, threshold, progress_cb=None, index_path='word_index.db'):
    """Usa el índice invertido si existe; sino cae al escaneo por disco."""
    if index_path and os.path.exists(index_path):
        return scan_with_index(index_path, terms, threshold)
    return scan_by_disk(stories_dir, terms, threshold, progress_cb)


def open_story_file(story_id, conn, stories_dir):
    if story_id is None:
        return
    row = conn.execute('SELECT filename FROM stories WHERE id=?', (story_id,)).fetchone()
    if not row or not row[0]:
        return
    path = os.path.join(stories_dir, row[0])
    if os.path.exists(path):
        import subprocess
        lector = os.path.expanduser('~/proyectos/lector')
        subprocess.Popen([f'{lector}/.venv/bin/python', f'{lector}/main.py', path])


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def load_tags(conn):
    return conn.execute('''
        SELECT t.id, t.name, COUNT(st.story_id) as cnt
        FROM user_tags t
        LEFT JOIN story_user_tags st ON st.tag_id = t.id
        GROUP BY t.id ORDER BY t.name
    ''').fetchall()


def search_stories(conn, query):
    q = f'%{query}%'
    return conn.execute('''
        SELECT id, COALESCE(title, filename) as label, COALESCE(author,'') as author
        FROM stories
        WHERE title LIKE ? OR author LIKE ? OR filename LIKE ?
        ORDER BY title LIMIT 50
    ''', (q, q, q)).fetchall()


def get_story_tags(conn, story_id):
    return conn.execute('''
        SELECT t.id, t.name FROM user_tags t
        JOIN story_user_tags st ON st.tag_id = t.id
        WHERE st.story_id = ?
        ORDER BY t.name
    ''', (story_id,)).fetchall()


def build_gui(db_path, stories_dir, index_path):
    conn = init_db(db_path)

    root = tk.Tk()
    root.title("Tagger de Historias")
    root.geometry("1000x680")

    paned = tk.PanedWindow(root, orient='horizontal', sashwidth=6)
    paned.pack(fill='both', expand=True, padx=6, pady=6)

    # ── Panel izquierdo: lista de tags ────────────────────────────────────
    left = ttk.LabelFrame(paned, text="Tags", padding=6)
    paned.add(left, minsize=200)

    tag_list = tk.Listbox(left, font=('monospace', 10))
    sb = ttk.Scrollbar(left, command=tag_list.yview)
    tag_list.configure(yscrollcommand=sb.set)
    tag_list.pack(side='left', fill='both', expand=True)
    sb.pack(side='right', fill='y')

    def refresh_tags():
        tag_list.delete(0, 'end')
        for row in load_tags(conn):
            tag_list.insert('end', f"{row['name']}  ({row['cnt']})")
        refresh_tag_combos()

    def selected_tag_id():
        sel = tag_list.curselection()
        if not sel:
            return None, None
        rows = load_tags(conn)
        if sel[0] >= len(rows):
            return None, None
        row = rows[sel[0]]
        return row['id'], row['name']

    btn_frame = ttk.Frame(left)
    btn_frame.pack(fill='x', pady=(4, 0))

    def new_tag():
        name = simpledialog.askstring("Nuevo tag", "Nombre del tag:", parent=root)
        if name and name.strip():
            try:
                conn.execute('INSERT INTO user_tags (name, created_at) VALUES (?,?)',
                             (name.strip(), datetime.now().isoformat()))
                conn.commit()
                refresh_tags()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def rename_tag():
        tid, tname = selected_tag_id()
        if tid is None:
            return
        new = simpledialog.askstring("Renombrar", f"Nuevo nombre para '{tname}':", parent=root)
        if new and new.strip():
            conn.execute('UPDATE user_tags SET name=? WHERE id=?', (new.strip(), tid))
            conn.commit()
            refresh_tags()

    def delete_tag():
        tid, tname = selected_tag_id()
        if tid is None:
            return
        if messagebox.askyesno("Borrar tag", f"¿Borrar '{tname}' y todas sus asignaciones?"):
            conn.execute('DELETE FROM user_tags WHERE id=?', (tid,))
            conn.commit()
            refresh_tags()

    ttk.Button(btn_frame, text="+ Nuevo", command=new_tag).pack(side='left', fill='x', expand=True)
    ttk.Button(btn_frame, text="✎", width=3, command=rename_tag).pack(side='left')
    ttk.Button(btn_frame, text="✗", width=3, command=delete_tag).pack(side='left')

    # ── Panel derecho: notebook ───────────────────────────────────────────
    right = ttk.Frame(paned)
    paned.add(right, minsize=600)

    nb = ttk.Notebook(right)
    nb.pack(fill='both', expand=True)

    # ── Tab 1: Reglas ─────────────────────────────────────────────────────
    tab_rules = ttk.Frame(nb, padding=10)
    nb.add(tab_rules, text="Reglas automáticas")

    ttk.Label(tab_rules, text="Tag destino:").grid(row=0, column=0, sticky='w', pady=4)
    rule_tag_var = tk.StringVar()
    rule_tag_cb = ttk.Combobox(tab_rules, textvariable=rule_tag_var, width=30, state='readonly')
    rule_tag_cb.grid(row=0, column=1, sticky='w', padx=6)

    ttk.Label(tab_rules, text="Términos (separados por coma):").grid(row=1, column=0, sticky='w', pady=4)
    terms_var = tk.StringVar()
    ttk.Entry(tab_rules, textvariable=terms_var, width=55).grid(row=1, column=1, sticky='ew', padx=6)

    ttk.Label(tab_rules, text="Umbral — total de ocurrencias ≥").grid(row=2, column=0, sticky='w', pady=4)
    thresh_var = tk.IntVar(value=5)
    ttk.Spinbox(tab_rules, from_=1, to=500, textvariable=thresh_var, width=6).grid(row=2, column=1, sticky='w', padx=6)

    preview_lbl = ttk.Label(tab_rules, text="", foreground='#336699')
    preview_lbl.grid(row=3, column=0, columnspan=2, sticky='w', pady=4)

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(tab_rules, variable=progress_var, maximum=100, length=400)
    progress_bar.grid(row=4, column=0, columnspan=2, sticky='ew', pady=2)

    scan_results = {'data': []}

    def do_scan(apply_after=False):
        terms = [t.strip() for t in terms_var.get().split(',') if t.strip()]
        if not terms:
            messagebox.showwarning("Aviso", "Ingresá al menos un término.")
            return
        tname = rule_tag_var.get()
        if not tname:
            messagebox.showwarning("Aviso", "Seleccioná un tag.")
            return

        preview_lbl.config(text="Escaneando...")
        progress_var.set(0)
        btn_preview.state(['disabled'])
        btn_apply.state(['disabled'])

        def run():
            def cb(i, total):
                root.after(0, lambda: progress_var.set(i / total * 100))
            results = scan_stories(stories_dir, terms, thresh_var.get(), cb, index_path)
            scan_results['data'] = results
            def done():
                preview_lbl.config(text=f"→ {len(results)} historias coinciden")
                progress_var.set(100)
                btn_preview.state(['!disabled'])
                btn_apply.state(['!disabled'])
                fill_results(results)
                if apply_after:
                    apply_rule()
            root.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    def apply_rule():
        if not scan_results['data']:
            messagebox.showwarning("Aviso", "Primero previsualizá la regla.")
            return
        tname = rule_tag_var.get()
        rows = {r['name']: r['id'] for r in load_tags(conn)}
        tid = rows.get(tname)
        if tid is None:
            return
        terms_json = json.dumps([t.strip() for t in terms_var.get().split(',') if t.strip()])
        n = len(scan_results['data'])
        for sid, score in scan_results['data']:
            conn.execute('INSERT OR REPLACE INTO story_user_tags (story_id, tag_id, source, score) VALUES (?,?,?,?)',
                         (sid, tid, 'rule', float(score)))
        conn.execute('INSERT INTO user_tag_rules (tag_id, terms, threshold, applied_at, match_count) VALUES (?,?,?,?,?)',
                     (tid, terms_json, thresh_var.get(), datetime.now().isoformat(), n))
        conn.commit()
        scan_results['data'] = []
        refresh_tags()
        refresh_rules_log()
        preview_lbl.config(text=f"✓ Tag '{tname}' aplicado a {n} historias")

    btn_preview = ttk.Button(tab_rules, text="▶ Previsualizar", command=lambda: do_scan(False))
    btn_preview.grid(row=5, column=0, pady=8, sticky='w')
    btn_apply = ttk.Button(tab_rules, text="✓ Aplicar tag", command=apply_rule)
    btn_apply.grid(row=5, column=1, pady=8, sticky='w', padx=6)

    # ── Tabla de historias que coinciden con la regla ────────────────────
    ttk.Label(tab_rules, text="Historias que coinciden (doble clic para abrir):").grid(
        row=6, column=0, columnspan=2, sticky='w', pady=(4, 0))
    res_cols = ('hits', 'id', 'title', 'author')
    results_tree = ttk.Treeview(tab_rules, columns=res_cols, show='headings', height=10)
    for c, h, w in [('hits', 'Ocurr.', 60), ('id', 'ID', 55),
                    ('title', 'Título', 300), ('author', 'Autor', 150)]:
        results_tree.heading(c, text=h)
        results_tree.column(c, width=w, anchor='w' if c in ('title', 'author') else 'center',
                            stretch=(c == 'title'))
    res_vsb = ttk.Scrollbar(tab_rules, orient='vertical', command=results_tree.yview)
    results_tree.configure(yscrollcommand=res_vsb.set)
    results_tree.grid(row=7, column=0, columnspan=2, sticky='nsew', pady=4)
    res_vsb.grid(row=7, column=2, sticky='ns', pady=4)
    res_iid_to_sid = {}

    def fill_results(results):
        for it in results_tree.get_children():
            results_tree.delete(it)
        res_iid_to_sid.clear()
        if not results:
            return
        top = sorted(results, key=lambda x: -x[1])[:500]  # más ocurrencias primero
        ids = [int(sid) for sid, _ in top]
        ph = ','.join('?' * len(ids))
        meta = {r[0]: (r[1], r[2]) for r in conn.execute(
            f"SELECT id, COALESCE(title, filename), COALESCE(author,'') FROM stories WHERE id IN ({ph})", ids)}
        for sid, hits in top:
            t, a = meta.get(sid, ('?', ''))
            iid = results_tree.insert('', 'end', values=(int(hits), sid, t, a))
            res_iid_to_sid[iid] = sid

    def res_double(_):
        s = results_tree.selection()
        if s:
            open_story_file(res_iid_to_sid.get(s[0]), conn, stories_dir)
    results_tree.bind('<Double-1>', res_double)

    # ── Historial de reglas (compacto, abajo) ─────────────────────────────
    ttk.Separator(tab_rules, orient='horizontal').grid(row=8, column=0, columnspan=3, sticky='ew', pady=6)
    ttk.Label(tab_rules, text="Historial de reglas:").grid(row=9, column=0, columnspan=2, sticky='w')

    rules_tree = ttk.Treeview(tab_rules, columns=('tag', 'terms', 'threshold', 'count', 'date'),
                               show='headings', height=4)
    for col, hdr, w in [('tag','Tag',100),('terms','Términos',250),('threshold','≥',40),
                         ('count','Historias',70),('date','Fecha',130)]:
        rules_tree.heading(col, text=hdr)
        rules_tree.column(col, width=w, anchor='w' if col in ('tag','terms') else 'center')
    rules_tree.grid(row=10, column=0, columnspan=2, sticky='nsew', pady=4)
    tab_rules.rowconfigure(7, weight=3)
    tab_rules.rowconfigure(10, weight=1)
    tab_rules.columnconfigure(1, weight=1)

    def refresh_rules_log():
        for i in rules_tree.get_children():
            rules_tree.delete(i)
        for row in conn.execute('''
            SELECT t.name, r.terms, r.threshold, r.match_count, r.applied_at
            FROM user_tag_rules r JOIN user_tags t ON t.id = r.tag_id
            ORDER BY r.applied_at DESC LIMIT 50
        '''):
            terms_preview = ', '.join(json.loads(row[1])[:4]) + ('...' if len(json.loads(row[1])) > 4 else '')
            rules_tree.insert('', 'end', values=(row[0], terms_preview, row[2], row[3], row[4][:16]))

    # ── Tab 2: Asignación manual ──────────────────────────────────────────
    tab_manual = ttk.Frame(nb, padding=10)
    nb.add(tab_manual, text="Asignación manual")

    ttk.Label(tab_manual, text="Buscar historia (título o autor):").grid(row=0, column=0, sticky='w')
    search_var = tk.StringVar()
    search_entry = ttk.Entry(tab_manual, textvariable=search_var, width=40)
    search_entry.grid(row=0, column=1, sticky='ew', padx=6)

    results_list = tk.Listbox(tab_manual, height=12, font=('monospace', 9))
    sb2 = ttk.Scrollbar(tab_manual, command=results_list.yview)
    results_list.configure(yscrollcommand=sb2.set)
    results_list.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=4)
    sb2.grid(row=1, column=2, sticky='ns', pady=4)
    tab_manual.rowconfigure(1, weight=1)
    tab_manual.columnconfigure(1, weight=1)

    search_data = {'rows': []}

    def do_search(*_):
        q = search_var.get().strip()
        if len(q) < 2:
            return
        rows = search_stories(conn, q)
        search_data['rows'] = rows
        results_list.delete(0, 'end')
        for r in rows:
            results_list.insert('end', f"[{r['id']:5d}] {r['label'][:45]}  —  {r['author'][:20]}")

    search_entry.bind('<Return>', do_search)
    ttk.Button(tab_manual, text="🔍", command=do_search).grid(row=0, column=2, padx=4)

    ttk.Separator(tab_manual, orient='horizontal').grid(row=2, column=0, columnspan=3, sticky='ew', pady=6)

    tags_lbl = ttk.Label(tab_manual, text="Tags asignados: —", wraplength=500, foreground='#336699')
    tags_lbl.grid(row=3, column=0, columnspan=3, sticky='w', pady=2)

    ttk.Label(tab_manual, text="Agregar tag:").grid(row=4, column=0, sticky='w', pady=4)
    add_tag_var = tk.StringVar()
    add_tag_cb = ttk.Combobox(tab_manual, textvariable=add_tag_var, width=25, state='readonly')
    add_tag_cb.grid(row=4, column=1, sticky='w', padx=6)

    ttk.Label(tab_manual, text="Quitar tag:").grid(row=5, column=0, sticky='w', pady=4)
    rm_tag_var = tk.StringVar()
    rm_tag_cb = ttk.Combobox(tab_manual, textvariable=rm_tag_var, width=25, state='readonly')
    rm_tag_cb.grid(row=5, column=1, sticky='w', padx=6)

    def selected_story_id():
        sel = results_list.curselection()
        if not sel or sel[0] >= len(search_data['rows']):
            return None
        return search_data['rows'][sel[0]]['id']

    def refresh_story_tags():
        sid = selected_story_id()
        if sid is None:
            tags_lbl.config(text="Tags asignados: —")
            rm_tag_cb['values'] = []
            return
        tags = get_story_tags(conn, sid)
        names = [t['name'] for t in tags]
        tags_lbl.config(text="Tags asignados: " + (', '.join(names) if names else '(ninguno)'))
        rm_tag_cb['values'] = names
        if names:
            rm_tag_cb.set(names[0])

    results_list.bind('<<ListboxSelect>>', lambda _: refresh_story_tags())

    def add_tag_to_story():
        sid = selected_story_id()
        tname = add_tag_var.get()
        if sid is None or not tname:
            return
        rows = {r['name']: r['id'] for r in load_tags(conn)}
        tid = rows.get(tname)
        if tid is None:
            return
        conn.execute('INSERT OR IGNORE INTO story_user_tags (story_id, tag_id, source) VALUES (?,?,?)',
                     (sid, tid, 'manual'))
        conn.commit()
        refresh_story_tags()
        refresh_tags()

    def rm_tag_from_story():
        sid = selected_story_id()
        tname = rm_tag_var.get()
        if sid is None or not tname:
            return
        rows = {r['name']: r['id'] for r in load_tags(conn)}
        tid = rows.get(tname)
        if tid is None:
            return
        conn.execute('DELETE FROM story_user_tags WHERE story_id=? AND tag_id=?', (sid, tid))
        conn.commit()
        refresh_story_tags()
        refresh_tags()

    ttk.Button(tab_manual, text="+ Agregar", command=add_tag_to_story).grid(row=4, column=2, padx=4)
    ttk.Button(tab_manual, text="− Quitar",  command=rm_tag_from_story).grid(row=5, column=2, padx=4)

    # ── Compartido: sync de combos de tags ───────────────────────────────
    def refresh_tag_combos():
        names = [r['name'] for r in load_tags(conn)]
        rule_tag_cb['values'] = names
        add_tag_cb['values'] = names
        if names:
            if not rule_tag_var.get():
                rule_tag_cb.set(names[0])
            if not add_tag_var.get():
                add_tag_cb.set(names[0])

    refresh_tags()
    refresh_rules_log()
    root.mainloop()
    conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default=os.path.expanduser('~/corpus-historias/stories.db'))
    p.add_argument('--stories-dir', default=os.path.expanduser('~/corpus-historias/stories/resto'))
    p.add_argument('--index', default=os.path.expanduser('~/corpus-historias/word_index.db'),
                   help='Índice invertido (si existe, previsualización instantánea)')
    args = p.parse_args()
    build_gui(args.db, args.stories_dir, args.index)


if __name__ == '__main__':
    main()
