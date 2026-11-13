"""Known bank formats, recognised from the file's header. Anything else uses a column mapping."""

from app.ingestion.connectors.nab_csv import NabCsvConnector

KNOWN_FORMATS = [NabCsvConnector()]


def recognise(header: list[str]):
    """The known connector whose format this header matches, or None."""
    for c in KNOWN_FORMATS:
        if c.matches(header):
            return c
    return None
