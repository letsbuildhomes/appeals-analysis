"""Vermont's towns and cities, and how to recognize a name meant for one of them.

The list is the Census Bureau's: every county subdivision in Vermont (towns, cities, gores and
grants), in vermont_towns.tsv. A name shared by a city and a town says which, as the state does:
"Rutland City" and "Rutland Town".
"""
import csv
import difflib
from pathlib import Path
import re

_FILE = Path(__file__).with_name('vermont_towns.tsv')
_ROWS = list(csv.DictReader((line for line in _FILE.open() if not line.startswith('#')), delimiter='\t'))

NAMES = [row['name'] for row in _ROWS]
KIND = {row['name']: row['kind'] for row in _ROWS}
SHARED = sorted({n.rsplit(' ', 1)[0] for n in NAMES if n.endswith((' City', ' Town'))})   # Barre, Newport, …


def _norm(text):
    text = text.casefold().replace('saint ', 'st ')
    words = re.sub(r"[^\w\s]", ' ', text).replace('_', ' ').split()
    return ' '.join('junction' if w == 'jct' else w for w in words)


def _bare(name):
    """A codebook name without the City or Town that tells shared names apart."""
    return name.rsplit(' ', 1)[0] if name.rsplit(' ', 1)[0] in SHARED else name


_BY_BARE = {}
for _name in NAMES:
    _BY_BARE.setdefault(_norm(_bare(_name)), []).append(_name)


def suggest(value):
    """The listed names most likely meant by `value`, such as "St. Johnsbury" for "Saint Johnsbury",
    "Rutland City" for "City of Rutland", or both Rutlands for "Rutland"."""
    text = _norm(value)
    text = re.sub(r'\b(vermont|vt)$', '', text).strip()
    kind = None
    prefix = re.match(r'^(?:the )?(town|city|village) of (.+)$', text)
    if prefix:
        kind, text = prefix.groups()
    else:
        suffix = re.match(r'^(.+) (town|city)$', text)
        if suffix:
            text, kind = suffix.groups()
    found = _BY_BARE.get(text, [])
    if kind in ('town', 'city') and len(found) > 1:
        found = [n for n in found if KIND[n] == kind] or found
    if found:
        return found
    close = difflib.get_close_matches(text, list(_BY_BARE), n=3, cutoff=0.8)
    return [n for c in close for n in _BY_BARE[c]]
