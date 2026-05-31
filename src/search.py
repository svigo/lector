import re
from dataclasses import dataclass
from typing import List


@dataclass
class Match:
    start: int
    end: int
    label: str  # 'match' | 'a' | 'b'


def simple_search(text: str, query: str, case_sensitive: bool = False) -> List[Match]:
    if not query:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    return [Match(m.start(), m.end(), 'match') for m in re.finditer(re.escape(query), text, flags)]


def fuzzy_search(text: str, query: str, case_sensitive: bool = False) -> List[Match]:
    """Each character becomes char+ to catch elongations like yes→yeeees."""
    if not query:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = ''.join(re.escape(c) + '+' for c in query)
    return [Match(m.start(), m.end(), 'match') for m in re.finditer(pattern, text, flags)]


def or_search(text: str, str_a: str, str_b: str, case_sensitive: bool = False) -> List[Match]:
    if not str_a and not str_b:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    result = []
    if str_a:
        result += [Match(m.start(), m.end(), 'a') for m in re.finditer(re.escape(str_a), text, flags)]
    if str_b:
        result += [Match(m.start(), m.end(), 'b') for m in re.finditer(re.escape(str_b), text, flags)]
    return sorted(result, key=lambda m: m.start)


def proximity_search(text: str, str_a: str, str_b: str, n: int, case_sensitive: bool = False) -> List[Match]:
    """Find pairs where gap from end of one to start of the other is < n chars."""
    if not str_a or not str_b:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE

    pos_a = [(m.start(), m.end()) for m in re.finditer(re.escape(str_a), text, flags)]
    pos_b = [(m.start(), m.end()) for m in re.finditer(re.escape(str_b), text, flags)]

    matched_a, matched_b = set(), set()

    for i, (as_, ae) in enumerate(pos_a):
        for j, (bs, be) in enumerate(pos_b):
            if bs >= ae:
                gap = bs - ae
            elif as_ >= be:
                gap = as_ - be
            else:
                gap = 0  # overlapping
            if gap < n:
                matched_a.add(i)
                matched_b.add(j)

    result = []
    for i in matched_a:
        s, e = pos_a[i]
        result.append(Match(s, e, 'a'))
    for j in matched_b:
        s, e = pos_b[j]
        result.append(Match(s, e, 'b'))

    return sorted(result, key=lambda m: m.start)
