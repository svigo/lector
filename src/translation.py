import logging
import requests
from spellchecker import SpellChecker
from typing import List

_spell = SpellChecker()

MYMEMORY_URL = "https://api.mymemory.translated.net/get"
PIXABAY_URL = "https://pixabay.com/api/"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/tmp/lector.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("lector.translation")


def translate_en_es(word: str) -> str:
    try:
        r = requests.get(MYMEMORY_URL, params={"q": word, "langpair": "en|es"}, timeout=5)
        r.raise_for_status()
        return r.json()["responseData"]["translatedText"]
    except Exception:
        return "(error al traducir)"


HEADERS = {"User-Agent": "lector/1.0 (text reader app; piscucho@gmail.com)"}


def _get_images_wikipedia(word: str, count: int = 3) -> List[bytes]:
    """Fetch thumbnails from the top Wikipedia search results for word."""
    log.debug("Wikipedia: buscando imágenes para '%s'", word)
    try:
        r = requests.get(WIKIPEDIA_API, headers=HEADERS, params={
            "action": "query",
            "generator": "search",
            "gsrsearch": word,
            "gsrlimit": 10,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 400,
            "format": "json",
        }, timeout=5)
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {}).values()
        all_urls = [(p["title"], p["thumbnail"]["source"]) for p in pages if "thumbnail" in p]
        log.debug("Wikipedia: %d páginas con thumbnail de %d totales", len(all_urls), len(list(pages)))
        urls = [u for _, u in all_urls[:count]]
        log.debug("Wikipedia: URLs seleccionadas: %s", urls)
        images = []
        for url in urls:
            try:
                data = requests.get(url, headers=HEADERS, timeout=5).content
                log.debug("Wikipedia: descargada imagen %d bytes de %s", len(data), url)
                images.append(data)
            except Exception as e:
                log.error("Wikipedia: error descargando %s: %s", url, e)
                images.append(b"")
        return images
    except Exception as e:
        log.error("Wikipedia: error en búsqueda: %s", e)
        return []


def _get_images_pixabay(word: str, api_key: str, count: int = 3) -> List[bytes]:
    log.debug("Pixabay: buscando imágenes para '%s'", word)
    try:
        r = requests.get(PIXABAY_URL, params={
            "key": api_key, "q": word, "image_type": "photo",
            "per_page": count, "safesearch": "true", "lang": "en",
        }, timeout=5)
        r.raise_for_status()
        hits = r.json().get("hits", [])
        log.debug("Pixabay: %d hits devueltos", len(hits))
        urls = [h["webformatURL"] for h in hits[:count]]
        log.debug("Pixabay: URLs: %s", urls)
        images = []
        for url in urls:
            try:
                data = requests.get(url, timeout=5).content
                log.debug("Pixabay: descargada imagen %d bytes de %s", len(data), url)
                images.append(data)
            except Exception as e:
                log.error("Pixabay: error descargando %s: %s", url, e)
                images.append(b"")
        return images
    except Exception as e:
        log.error("Pixabay: error en búsqueda: %s", e)
        return []


def correct_word(word: str) -> str:
    corrected = _spell.correction(word.lower())
    if corrected and corrected != word.lower():
        log.debug("Spell correction: '%s' → '%s'", word, corrected)
    return corrected or word


def get_images(word: str, api_key: str, count: int = 3) -> List[bytes]:
    """Returns up to count image bytes. Uses Pixabay if key available, falls back to Wikipedia."""
    if api_key:
        images = _get_images_pixabay(word, api_key, count)
        if images:
            return images
        log.debug("Pixabay sin resultados para '%s', usando Wikipedia como fallback", word)
    return _get_images_wikipedia(word, count)
