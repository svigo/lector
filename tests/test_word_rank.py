import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'story_classifier'))
import word_rank


@pytest.fixture
def index_db(tmp_path):
    """Índice mínimo con dos historias.

    #1: 'whip' 10 veces + 'whipping' 5, total 1000 palabras
    #2: 'whip' 3 veces + 'castle' 4,    total 100 palabras
    """
    path = str(tmp_path / 'word_index.db')
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE word_index (word TEXT, story_id INTEGER, count INTEGER)')
    conn.execute('CREATE TABLE exact_index (word TEXT, story_id INTEGER, count INTEGER)')
    conn.executemany('INSERT INTO word_index VALUES (?,?,?)', [
        ('whip', 1, 15), ('other', 1, 985),
        ('whip', 2, 3), ('castl', 2, 4), ('other', 2, 93),
    ])
    conn.executemany('INSERT INTO exact_index VALUES (?,?,?)', [
        ('whip', 1, 10), ('whipping', 1, 5), ('other', 1, 985),
        ('whip', 2, 3), ('castle', 2, 4), ('other', 2, 93),
    ])
    conn.commit()
    conn.close()
    return path


class TestStem:
    def test_agrupa_variantes(self):
        assert word_rank.stem('whipping') == word_rank.stem('whip')

    def test_case_insensitive(self):
        assert word_rank.stem('WHIP') == word_rank.stem('whip')


class TestWordCounts:
    def test_stem_suma_variantes(self, index_db):
        conn = sqlite3.connect(index_db)
        assert word_rank.word_counts(conn, ['whipping'])[1] == 15

    def test_exacta_no_suma_variantes(self, index_db):
        conn = sqlite3.connect(index_db)
        assert word_rank.word_counts(conn, ['whip'], exact=True)[1] == 10

    def test_varias_palabras_es_and(self, index_db):
        conn = sqlite3.connect(index_db)
        # solo la #2 tiene ambas
        assert set(word_rank.word_counts(conn, ['whip', 'castle'])) == {2}

    def test_and_suma_ocurrencias(self, index_db):
        conn = sqlite3.connect(index_db)
        assert word_rank.word_counts(conn, ['whip', 'castle'])[2] == 7

    def test_palabra_repetida_no_rompe_el_and(self, index_db):
        conn = sqlite3.connect(index_db)
        assert set(word_rank.word_counts(conn, ['whip', 'whip'])) == {1, 2}

    def test_sin_palabras(self, index_db):
        conn = sqlite3.connect(index_db)
        assert word_rank.word_counts(conn, []) == {}

    def test_palabra_inexistente(self, index_db):
        conn = sqlite3.connect(index_db)
        assert word_rank.word_counts(conn, ['zzzz']) == {}

    def test_exacta_sin_tabla_avisa(self, tmp_path):
        path = str(tmp_path / 'viejo.db')
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE word_index (word TEXT, story_id INTEGER, count INTEGER)')
        conn.commit()
        with pytest.raises(RuntimeError, match='build_index'):
            word_rank.word_counts(conn, ['whip'], exact=True)


class TestRankByWords:
    def test_ordena_por_ocurrencias(self, index_db):
        r = word_rank.rank_by_words(index_db, ['whip'])
        assert [x['id'] for x in r] == [1, 2]
        assert r[0]['rank'] == 1

    def test_densidad_invierte_el_orden(self, index_db):
        # #1 tiene más veces (15 vs 3), pero #2 la concentra más (30‰ vs 15‰)
        r = word_rank.rank_by_words(index_db, ['whip'], by_density=True)
        assert [x['id'] for x in r] == [2, 1]

    def test_per_1k(self, index_db):
        r = word_rank.rank_by_words(index_db, ['whip'])
        assert r[0]['per_1k'] == pytest.approx(15.0)

    def test_top_n(self, index_db):
        assert len(word_rank.rank_by_words(index_db, ['whip'], top_n=1)) == 1

    def test_sin_resultados(self, index_db):
        assert word_rank.rank_by_words(index_db, ['zzzz']) == []

    def test_story_totals_se_cachea(self, index_db):
        word_rank.rank_by_words(index_db, ['whip'])
        conn = sqlite3.connect(index_db)
        assert conn.execute('SELECT total FROM story_totals WHERE story_id=1').fetchone()[0] == 1000


class TestStoriesWithWords:
    def test_devuelve_ids(self, index_db):
        assert word_rank.stories_with_words(index_db, ['whip']) == {1, 2}

    def test_and(self, index_db):
        assert word_rank.stories_with_words(index_db, ['whip', 'castle']) == {2}
