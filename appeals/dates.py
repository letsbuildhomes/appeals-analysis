"""Which dates are plausible in this court's records.

The Environmental Court was created in 1990, so no listing, docket or
decision can be dated before then, and none can be dated after today. Every
date read from the listing, a docket number or a model's reply is checked
against this one rule.
"""
from datetime import date
import re

FIRST_YEAR = 1990
DATE = re.compile(r'^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$')


def last_year():
    return date.today().year


def plausible_year(year):
    return FIRST_YEAR <= year <= last_year()


def problem(text):
    """Why a YYYY, YYYY-MM or YYYY-MM-DD date is not acceptable, or None when it is."""
    m = DATE.match(text) if isinstance(text, str) else None
    if not m:
        return 'expected YYYY, YYYY-MM or YYYY-MM-DD'
    year, month, day = (int(part) if part else None for part in m.groups())
    if not plausible_year(year):
        return f'the year {year} is outside {FIRST_YEAR}–{last_year()}'
    try:
        date(year, month or 1, day or 1)
    except ValueError:
        return f'{text} is not a calendar date'
    return None
