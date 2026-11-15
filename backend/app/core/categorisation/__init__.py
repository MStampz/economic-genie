"""Automatic categorisation: a chain of matchers over a transaction's text, amount and bank data.

See engine.py for the order, text.py for how payee names are cleaned, library.py for built-ins.
"""

from app.core.categorisation.engine import Categoriser, Decision, Facts
from app.core.categorisation.text import payee_key

__all__ = ["Categoriser", "Decision", "Facts", "payee_key"]
