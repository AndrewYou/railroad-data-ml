"""USDA AgTransport (Socrata) API. Public, no key needed."""
import datetime as dt
import logging
from collections.abc import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

BASE_URL = "https://agtransport.usda.gov"
PAGE_SIZE = 50_000
TIMEOUT = (10, 120)  # seconds to connect, seconds of silence before retrying

log = logging.getLogger(__name__)

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))))


def last_updated(dataset_id: str) -> dt.datetime:
    """When USDA last changed the dataset's rows (metadata only; one small request)."""
    metadata = _get(f"{BASE_URL}/api/views/{dataset_id}.json")
    return dt.datetime.fromtimestamp(metadata["rowsUpdatedAt"], tz=dt.timezone.utc)


def fetch_rows(dataset_id: str, since: dt.date) -> Iterator[dict]:
    """Every row with a week-ending date on or after `since`, fetched page by page."""
    offset = 0
    while True:
        page = _get(f"{BASE_URL}/resource/{dataset_id}.json", params={
            "$where": f"date >= '{since}'",
            "$order": ":id",  # stable order so pages don't overlap
            "$limit": PAGE_SIZE,
            "$offset": offset,
        })
        log.info("%s: fetched %s rows", dataset_id, offset + len(page))
        yield from page
        if len(page) < PAGE_SIZE:
            return
        offset += PAGE_SIZE


def _get(url: str, params: dict | None = None):
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()
