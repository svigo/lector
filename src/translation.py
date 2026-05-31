import requests
from typing import List

MYMEMORY_URL = "https://api.mymemory.translated.net/get"
PIXABAY_URL = "https://pixabay.com/api/"


def translate_en_es(word: str) -> str:
    try:
        r = requests.get(MYMEMORY_URL, params={"q": word, "langpair": "en|es"}, timeout=5)
        r.raise_for_status()
        return r.json()["responseData"]["translatedText"]
    except Exception:
        return "(error al traducir)"


def get_images(word: str, api_key: str, count: int = 3) -> List[bytes]:
    """Returns list of image bytes (up to count). Empty list if no key or error."""
    if not api_key:
        return []
    try:
        r = requests.get(PIXABAY_URL, params={
            "key": api_key, "q": word, "image_type": "photo",
            "per_page": count, "safesearch": "true", "lang": "en",
        }, timeout=5)
        r.raise_for_status()
        urls = [h["webformatURL"] for h in r.json().get("hits", [])[:count]]
        images = []
        for url in urls:
            try:
                images.append(requests.get(url, timeout=5).content)
            except Exception:
                images.append(b"")
        return images
    except Exception:
        return []
