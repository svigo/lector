#!/usr/bin/env python3
"""
Scraper de bdsmlibrary.com → stories.db (SQLite)
Uso: python3 scraper.py --stories-dir /path/to/stories/resto/ [--delay 1.5] [--db stories.db] [--test]

--test     procesa solo 5 historias y muestra detalle de lo parseado
--delay N  segundos entre requests (default 1.5)
--db PATH  base de datos SQLite de salida (default stories.db)
"""

import os, sys, glob, time, sqlite3, argparse, re
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString
import requests

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id            INTEGER PRIMARY KEY,
    filename      TEXT,
    title         TEXT,
    author        TEXT,
    author_id     INTEGER,
    synopsis      TEXT,
    published     TEXT,
    size_kb       INTEGER,
    rating        REAL,
    votes         INTEGER,
    readers_total INTEGER,
    readers_month INTEGER,
    scraped_at    TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    story_id INTEGER NOT NULL REFERENCES stories(id),
    tag      TEXT    NOT NULL,
    PRIMARY KEY (story_id, tag)
);
CREATE TABLE IF NOT EXISTS shelves (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id     INTEGER NOT NULL REFERENCES stories(id),
    shelf_name   TEXT,
    username     TEXT,
    shelf_url    TEXT,
    user_comment TEXT
);
"""

SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'


def parse_page(story_id, html):
    soup = BeautifulSoup(html, 'html.parser')
    data = {'id': story_id, 'tags': [], 'shelves': []}

    # Título y autor (tabla con bgcolor="#CCCCFF")
    header = soup.find('table', attrs={'bgcolor': '#CCCCFF'})
    if header:
        title_font = header.find('font', attrs={'face': 'Verdana, Arial, Helvetica, sans-serif'})
        if title_font:
            data['title'] = title_font.get_text(strip=True)
        author_link = header.find('a', href=re.compile(r'author\.php\?authorid='))
        if author_link:
            data['author'] = author_link.get_text(strip=True)
            m = re.search(r'authorid=(\d+)', author_link['href'])
            if m:
                data['author_id'] = int(m.group(1))
        m = re.search(r'\((\d+(?:\.\d+)?)/10,\s*(\d+)\s*votes?\)', header.get_text())
        if m:
            data['rating'] = float(m.group(1))
            data['votes'] = int(m.group(2))

    # Tags (links con searchcode=)
    for a in soup.find_all('a', href=re.compile(r'searchcode=')):
        m = re.search(r'searchcode=(.+)', a['href'])
        if m:
            data['tags'].append(m.group(1))

    # Synopsis (el <b>Synopsis:</b> tiene el texto como hermano directo)
    for b in soup.find_all('b'):
        if b.get_text(strip=True) == 'Synopsis:':
            parts = []
            for child in b.find_parent().children:
                if child == b:
                    continue
                text = str(child) if isinstance(child, NavigableString) else child.get_text()
                parts.append(text)
            synopsis = ' '.join(parts).strip()
            if synopsis:
                data['synopsis'] = synopsis
            break

    # Size
    for b in soup.find_all('b'):
        if b.get_text(strip=True) == 'Size:':
            m = re.search(r'(\d+)\s*kb', b.find_parent().get_text(), re.IGNORECASE)
            if m:
                data['size_kb'] = int(m.group(1))
            break

    # Fecha de publicación
    for b in soup.find_all('b'):
        if 'Added on' in b.get_text():
            m = re.search(r'Added on:\s*(.+)', b.find_parent().get_text())
            if m:
                data['published'] = m.group(1).strip()
            break

    # Lectores
    for b in soup.find_all('b'):
        txt = b.get_text(strip=True)
        m = re.match(r'Total (\d+) readers', txt)
        if m:
            data['readers_total'] = int(m.group(1))
        m = re.match(r'This month (\d+) readers', txt)
        if m:
            data['readers_month'] = int(m.group(1))

    # Shelves: cada shelf es una <table> dentro del td.sidemenu, después de "This story is listed in"
    listed_marker = soup.find(string=lambda t: t and 'This story is listed in' in str(t))
    if listed_marker:
        container = listed_marker.find_parent('td')
        if container:
            for table in container.find_all('table'):
                shelf_link = table.find('a', href=re.compile(r'shelf\.php\?groupid='))
                if not shelf_link:
                    continue
                shelf_name = shelf_link.get_text(strip=True)
                shelf_url = 'https://www.bdsmlibrary.com' + shelf_link['href'].split('#')[0]
                user_link = table.find('a', href=re.compile(r'user\.php\?action=profile'))
                username = user_link.get_text(strip=True) if user_link else None

                # Comentario: NavigableString en la segunda fila, antes del <div>
                comment = None
                rows = table.find_all('tr')
                if len(rows) >= 2:
                    second_td = rows[1].find('td')
                    if second_td:
                        parts = []
                        for child in second_td.children:
                            if getattr(child, 'name', None) == 'div':
                                break
                            if isinstance(child, NavigableString):
                                t = str(child).strip()
                                if t:
                                    parts.append(t)
                        if parts:
                            comment = ' '.join(parts)

                data['shelves'].append({
                    'shelf_name': shelf_name,
                    'username': username,
                    'shelf_url': shelf_url,
                    'user_comment': comment,
                })

    data['scraped_at'] = datetime.utcnow().isoformat()
    return data


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def already_scraped(conn, story_id):
    row = conn.execute('SELECT scraped_at FROM stories WHERE id=?', (story_id,)).fetchone()
    return row is not None


def insert(conn, data, filename=None):
    conn.execute('''
        INSERT OR REPLACE INTO stories
        (id, filename, title, author, author_id, synopsis, published, size_kb,
         rating, votes, readers_total, readers_month, scraped_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        data['id'], filename,
        data.get('title'), data.get('author'), data.get('author_id'),
        data.get('synopsis'), data.get('published'), data.get('size_kb'),
        data.get('rating'), data.get('votes'),
        data.get('readers_total'), data.get('readers_month'),
        data.get('scraped_at'),
    ))
    for tag in data.get('tags', []):
        conn.execute('INSERT OR IGNORE INTO tags (story_id, tag) VALUES (?,?)', (data['id'], tag))
    # Borrar shelves previos para este story antes de reinsertar (por si se re-scrapea)
    conn.execute('DELETE FROM shelves WHERE story_id=?', (data['id'],))
    for sh in data.get('shelves', []):
        conn.execute(
            'INSERT INTO shelves (story_id, shelf_name, username, shelf_url, user_comment) VALUES (?,?,?,?,?)',
            (data['id'], sh['shelf_name'], sh['username'], sh['shelf_url'], sh['user_comment'])
        )
    conn.commit()


def get_story_ids(stories_dir):
    ids = {}
    for path in sorted(glob.glob(os.path.join(stories_dir, '**', '*.txt'), recursive=True)):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('ID:'):
                        sid = int(line.split(':', 1)[1].strip())
                        ids[sid] = os.path.basename(path)
                        break
                    if line.startswith('---'):
                        break
        except Exception:
            pass
    return ids


def main():
    p = argparse.ArgumentParser(description='Scraper de bdsmlibrary.com')
    p.add_argument('--stories-dir', default=os.path.expanduser('~/corpus-historias/stories/resto'))
    p.add_argument('--db', default=os.path.expanduser('~/corpus-historias/stories.db'))
    p.add_argument('--delay', type=float, default=1.5)
    p.add_argument('--test', action='store_true', help='Solo 5 historias, muestra detalle')
    args = p.parse_args()

    conn = init_db(args.db)
    story_ids = get_story_ids(args.stories_dir)
    print(f'{len(story_ids)} IDs en archivos locales')

    pending = [(sid, fname) for sid, fname in sorted(story_ids.items())
               if not already_scraped(conn, sid)]
    print(f'{len(pending)} pendientes de scrapear')
    if not pending:
        print('Nada que hacer.')
        return

    if args.test:
        pending = pending[:5]
        print('Modo test: 5 historias\n')

    ok = err = 0
    total = len(pending)
    for i, (sid, fname) in enumerate(pending):
        url = f'https://www.bdsmlibrary.com/stories/story.php?storyid={sid}'
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 404:
                conn.execute('INSERT OR IGNORE INTO stories (id, filename, scraped_at) VALUES (?,?,?)',
                             (sid, fname, 'NOT_FOUND'))
                conn.commit()
                print(f'  [{i+1}/{total}] {sid} → 404')
                continue
            r.raise_for_status()
            data = parse_page(sid, r.text)
            insert(conn, data, fname)
            ok += 1
            if args.test:
                print(f'  [{i+1}/{total}] ID={sid} "{data.get("title","?")}"')
                print(f'    Autor: {data.get("author")} (id={data.get("author_id")})')
                print(f'    Tags: {data.get("tags")}')
                print(f'    Rating: {data.get("rating")}/10 ({data.get("votes")} votos)')
                print(f'    Lectores: {data.get("readers_total")} total, {data.get("readers_month")} este mes')
                print(f'    Fecha: {data.get("published")} | Tamaño: {data.get("size_kb")} kb')
                print(f'    Synopsis: {(data.get("synopsis") or "")[:100]}...')
                print(f'    Shelves ({len(data["shelves"])}):', [s["shelf_name"] for s in data["shelves"]])
                print()
            else:
                pct = (i + 1) / total * 100
                print(f'  [{i+1}/{total} {pct:.1f}%] {sid} — {data.get("title","?")} '
                      f'| tags:{len(data["tags"])} shelves:{len(data["shelves"])}', flush=True)
        except Exception as e:
            err += 1
            print(f'  [{i+1}/{total}] {sid} → ERROR: {e}')

        if i < total - 1:
            time.sleep(args.delay)

    print(f'\nFin. OK:{ok}  Errores:{err}  Base de datos: {args.db}')
    conn.close()


if __name__ == '__main__':
    main()
