"""Load and validate sites.yaml."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import yaml

# Days between captures for each repeating schedule.
SCHEDULE_DAYS = {"weekly": 7, "monthly": 30}
SCHEDULES = {"once", "off", *SCHEDULE_DAYS}
SCOPES = {"host", "domain", "prefix"}

DEFAULT_DOCUMENT_EXTENSIONS = [
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".zip", ".epub", ".xml", ".json",
]

DEFAULTS: Dict[str, Any] = {
    "schedule": "once",
    "scope": "host",
    "offsite_documents": True,
    "site_files": False,
    "respect_robots": True,
    "use_sitemap": True,
    "page_limit": 0,
    "time_limit_hours": 5,
    "workers": 4,
    "exclude": [],
    "max_parts": 50,
    "max_offsite_documents": 2000,
    "document_extensions": DEFAULT_DOCUMENT_EXTENSIONS,
}

# GitHub-hosted runners stop a job at 6 hours; leave time for extraction and upload.
MAX_TIME_LIMIT_HOURS = 5


class ConfigError(ValueError):
    pass


def slugify(url: str) -> str:
    """Turn a URL into a short name, e.g. https://www.ndis.gov.au/about -> ndis-gov-au-about."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    slug = re.sub(r"[^a-z0-9]+", "-", f"{host} {parts.path.lower()}").strip("-")
    return slug[:60].strip("-")


def normalise_site(raw: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not raw.get("url"):
        raise ConfigError(f"Each site needs a url: {raw!r}")
    site = {**DEFAULTS, **defaults, **raw}
    url = str(site["url"]).strip()
    if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
        raise ConfigError(f"Not a web address: {url}")
    site["url"] = url
    site["slug"] = slugify(str(site["name"])) if site.get("name") else slugify(url)
    if not site["slug"]:
        raise ConfigError(f"Could not make a name from {url}; add name:")
    if site["schedule"] not in SCHEDULES:
        raise ConfigError(f"{url}: schedule must be one of {sorted(SCHEDULES)}")
    if site["scope"] not in SCOPES:
        raise ConfigError(f"{url}: scope must be one of {sorted(SCOPES)}")
    for key in ("page_limit", "workers", "max_parts", "max_offsite_documents"):
        site[key] = int(site[key])
    site["time_limit_hours"] = min(float(site["time_limit_hours"]), MAX_TIME_LIMIT_HOURS)
    if isinstance(site["exclude"], str):
        site["exclude"] = [site["exclude"]]
    site["document_extensions"] = [
        e.lower() if e.startswith(".") else "." + e.lower() for e in site["document_extensions"]
    ]
    return site


def load_sites(path: Path) -> List[Dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    defaults = data.get("defaults") or {}
    unknown = set(defaults) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"Unknown defaults: {sorted(unknown)}")
    sites = [normalise_site(raw, defaults) for raw in data.get("sites") or []]
    seen: Dict[str, str] = {}
    for site in sites:
        if site["slug"] in seen:
            raise ConfigError(
                f"{site['url']} and {seen[site['slug']]} have the same name "
                f"'{site['slug']}'; give one a different name:"
            )
        seen[site["slug"]] = site["url"]
    return sites


DASHBOARD_DEFAULTS = {"markdown": True, "web_page": True}


def load_dashboard_settings(path: Path) -> Dict[str, bool]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    raw = data.get("dashboard") or {}
    unknown = set(raw) - set(DASHBOARD_DEFAULTS)
    if unknown:
        raise ConfigError(f"Unknown dashboard settings: {sorted(unknown)}")
    return {**DASHBOARD_DEFAULTS, **{k: bool(v) for k, v in raw.items()}}


def find_site(sites: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    key = key.strip()
    for site in sites:
        if key in (site["slug"], site["url"]):
            return site
    return None
