"""One name per Indian state for the mandi-price data.

data.gov.in spells some states differently from maps / geocoding
("Keralam", "Chattisgarh", "NCT of Delhi", "Pondicherry"). Without this, a
farm in Kerala finds no prices, and the same state shows up twice.
"""
from django.db.models import Q

_ALIASES = {
    "keralam": "Kerala",
    "chattisgarh": "Chhattisgarh",
    "nct of delhi": "Delhi",
    "delhi": "Delhi",
    "pondicherry": "Puducherry",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "orissa": "Odisha",
    "uttaranchal": "Uttarakhand",
    "jammu & kashmir": "Jammu and Kashmir",
    "telengana": "Telangana",
}


def canonical_state(name):
    """Display name for a state, whatever spelling the data or user used."""
    if not name:
        return name
    clean = " ".join(str(name).split())
    return _ALIASES.get(clean.lower(), clean)


def state_q(name, field="state"):
    """Q matching every spelling of the given state (case-insensitive)."""
    target = canonical_state(name).lower()
    spellings = {target} | {alias for alias, canon in _ALIASES.items() if canon.lower() == target}
    q = Q()
    for s in spellings:
        q |= Q(**{f"{field}__iexact": s})
    return q
