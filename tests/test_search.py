import pytest
from src.search import simple_search, fuzzy_search, or_search, proximity_search


class TestSimpleSearch:
    def test_finds_single(self):
        m = simple_search("hello world", "world")
        assert len(m) == 1
        assert m[0].start == 6 and m[0].end == 11

    def test_finds_multiple(self):
        assert len(simple_search("cat and cat and cat", "cat")) == 3

    def test_case_insensitive_default(self):
        assert len(simple_search("Hello HELLO hello", "hello")) == 3

    def test_case_sensitive(self):
        assert len(simple_search("Hello HELLO hello", "hello", case_sensitive=True)) == 1

    def test_empty_query(self):
        assert simple_search("some text", "") == []

    def test_no_match(self):
        assert simple_search("hello world", "xyz") == []

    def test_label(self):
        assert simple_search("abc", "abc")[0].label == 'match'


class TestFuzzySearch:
    def test_finds_exact(self):
        assert len(fuzzy_search("yes no", "yes")) == 1

    def test_finds_elongated_vowel(self):
        assert len(fuzzy_search("yeeees!", "yes")) == 1

    def test_finds_elongated_consonant(self):
        assert len(fuzzy_search("yesssss!", "yes")) == 1

    def test_finds_mixed_elongation(self):
        assert len(fuzzy_search("yeeeessssss", "yes")) == 1

    def test_finds_multiple_elongated(self):
        assert len(fuzzy_search("yeeees and yesssss", "yes")) == 2

    def test_no_match_missing_char(self):
        # "ye" without 's' should not match "yes"
        assert fuzzy_search("yeeeee", "yes") == []

    def test_empty_query(self):
        assert fuzzy_search("some text", "") == []

    def test_label(self):
        assert fuzzy_search("yes", "yes")[0].label == 'match'


class TestOrSearch:
    def test_finds_both_terms(self):
        m = or_search("cat and dog", "cat", "dog")
        assert len(m) == 2
        assert {x.label for x in m} == {'a', 'b'}

    def test_multiple_of_each(self):
        m = or_search("cat dog cat", "cat", "dog")
        assert len([x for x in m if x.label == 'a']) == 2
        assert len([x for x in m if x.label == 'b']) == 1

    def test_sorted_by_position(self):
        m = or_search("dog cat", "cat", "dog")
        assert m[0].start < m[1].start

    def test_only_a_present(self):
        m = or_search("cat here", "cat", "dog")
        assert len(m) == 1 and m[0].label == 'a'

    def test_empty_both(self):
        assert or_search("text", "", "") == []


class TestProximitySearch:
    def test_within_range(self):
        # "cat" ends at 3, "dog" starts at 8, gap=5 < 10
        m = proximity_search("cat   dog", "cat", "dog", n=10)
        assert len(m) == 2

    def test_outside_range(self):
        # "cat" ends at 3, "dog" starts at 8, gap=5, n=5 → not < 5
        assert proximity_search("cat     dog", "cat", "dog", n=5) == []

    def test_exact_boundary(self):
        # gap=5, n=6 → included
        m = proximity_search("cat   dog", "cat", "dog", n=6)
        assert len(m) == 2

    def test_adjacent_no_gap(self):
        # "catdog" → gap=0 < 1
        m = proximity_search("catdog", "cat", "dog", n=1)
        assert len(m) == 2

    def test_reversed_order(self):
        # "dog" before "cat"
        m = proximity_search("dog   cat", "cat", "dog", n=10)
        assert len(m) == 2

    def test_labels(self):
        m = proximity_search("cat   dog", "cat", "dog", n=10)
        assert {x.label for x in m} == {'a', 'b'}

    def test_empty_inputs(self):
        assert proximity_search("hello world", "", "", n=5) == []
        assert proximity_search("hello world", "hello", "", n=5) == []

    def test_multiple_pairs(self):
        # cat...dog cat...dog — all 4 should be marked
        text = "cat  dog  cat  dog"
        m = proximity_search(text, "cat", "dog", n=5)
        assert len(m) == 4

    def test_sorted_by_position(self):
        m = proximity_search("cat  dog", "cat", "dog", n=10)
        assert m[0].start < m[1].start
