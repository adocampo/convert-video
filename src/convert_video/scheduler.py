"""Schedule engine for pausing conversions based on time windows and electricity prices."""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror, request as urlrequest

log = logging.getLogger(__name__)

# ── Bidding-zone catalogue ──────────────────────────────────────────────────
# Curated list covering the Energy-Charts ``bzn`` parameter *and*
# the ENTSO-E area EIC codes that the Transparency Platform accepts for
# the Day-Ahead Prices document (A44).
# fmt: off
BIDDING_ZONES: List[Dict[str, str]] = [
    {"code": "AL",    "label": "Albania",                "entsoe_eic": "10YAL-KESH-----5"},
    {"code": "AT",    "label": "Austria",                "entsoe_eic": "10YAT-APG------L"},
    {"code": "BE",    "label": "Belgium",                "entsoe_eic": "10YBE----------2"},
    {"code": "BA",    "label": "Bosnia and Herzegovina", "entsoe_eic": "10YBA-JPCC-----D"},
    {"code": "BG",    "label": "Bulgaria",               "entsoe_eic": "10YCA-BULGARIA-R"},
    {"code": "HR",    "label": "Croatia",                "entsoe_eic": "10YHR-HEP------M"},
    {"code": "CZ",    "label": "Czech Republic",         "entsoe_eic": "10YCZ-CEPS-----N"},
    {"code": "DK1",   "label": "Denmark West",           "entsoe_eic": "10YDK-1--------W"},
    {"code": "DK2",   "label": "Denmark East",           "entsoe_eic": "10YDK-2--------M"},
    {"code": "EE",    "label": "Estonia",                "entsoe_eic": "10Y1001A1001A39I"},
    {"code": "FI",    "label": "Finland",                "entsoe_eic": "10YFI-1--------U"},
    {"code": "FR",    "label": "France",                 "entsoe_eic": "10YFR-RTE------C"},
    {"code": "DE-LU", "label": "Germany / Luxembourg",   "entsoe_eic": "10Y1001A1001A82H"},
    {"code": "GR",    "label": "Greece",                 "entsoe_eic": "10YGR-HTSO-----Y"},
    {"code": "HU",    "label": "Hungary",                "entsoe_eic": "10YHU-MAVIR----U"},
    {"code": "IE-SEM","label": "Ireland (SEM)",          "entsoe_eic": "10Y1001A1001A59C"},
    {"code": "IT-NO", "label": "Italy North",            "entsoe_eic": "10Y1001A1001A73I"},
    {"code": "IT-CN", "label": "Italy Centre-North",     "entsoe_eic": "10Y1001A1001A70O"},
    {"code": "IT-CS", "label": "Italy Centre-South",     "entsoe_eic": "10Y1001A1001A71M"},
    {"code": "IT-SO", "label": "Italy South",            "entsoe_eic": "10Y1001A1001A788"},
    {"code": "IT-SI", "label": "Italy Sicily",           "entsoe_eic": "10Y1001A1001A74G"},
    {"code": "IT-SA", "label": "Italy Sardinia",         "entsoe_eic": "10Y1001A1001A75E"},
    {"code": "LV",    "label": "Latvia",                 "entsoe_eic": "10YLV-1001A00074"},
    {"code": "LT",    "label": "Lithuania",              "entsoe_eic": "10YLT-1001A0008Q"},
    {"code": "ME",    "label": "Montenegro",             "entsoe_eic": "10YCS-CG-TSO---S"},
    {"code": "NL",    "label": "Netherlands",            "entsoe_eic": "10YNL----------L"},
    {"code": "NO1",   "label": "Norway Oslo",            "entsoe_eic": "10YNO-1--------2"},
    {"code": "NO2",   "label": "Norway Kristiansand",    "entsoe_eic": "10YNO-2--------T"},
    {"code": "NO3",   "label": "Norway Trondheim",       "entsoe_eic": "10YNO-3--------J"},
    {"code": "NO4",   "label": "Norway Tromsø",          "entsoe_eic": "10YNO-4--------9"},
    {"code": "NO5",   "label": "Norway Bergen",          "entsoe_eic": "10Y1001A1001A48H"},
    {"code": "PL",    "label": "Poland",                 "entsoe_eic": "10YPL-AREA-----S"},
    {"code": "PT",    "label": "Portugal",               "entsoe_eic": "10YPT-REN------W"},
    {"code": "RO",    "label": "Romania",                "entsoe_eic": "10YRO-TEL------P"},
    {"code": "RS",    "label": "Serbia",                 "entsoe_eic": "10YCS-SERBIATSOV"},
    {"code": "SK",    "label": "Slovakia",               "entsoe_eic": "10YSK-SEPS-----K"},
    {"code": "SI",    "label": "Slovenia",               "entsoe_eic": "10YSI-ELES-----O"},
    {"code": "ES",    "label": "Spain",                  "entsoe_eic": "10YES-REE------0"},
    {"code": "SE1",   "label": "Sweden Luleå",           "entsoe_eic": "10Y1001A1001A44P"},
    {"code": "SE2",   "label": "Sweden Sundsvall",       "entsoe_eic": "10Y1001A1001A45N"},
    {"code": "SE3",   "label": "Sweden Stockholm",       "entsoe_eic": "10Y1001A1001A46L"},
    {"code": "SE4",   "label": "Sweden Malmö",           "entsoe_eic": "10Y1001A1001A47J"},
    {"code": "CH",    "label": "Switzerland",            "entsoe_eic": "10YCH-SWISSGRIDZ"},
    {"code": "UK",    "label": "United Kingdom",         "entsoe_eic": "10YGB----------A"},
]
# fmt: on

ZONE_CODE_SET = {z["code"] for z in BIDDING_ZONES}

WEEKDAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_INTS = {v: k for k, v in WEEKDAY_NAMES.items()}

# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class ManualRule:
    """A single time-window rule.

    ``days``  – list of weekday ints (0=Mon … 6=Sun).  Empty means every day.
    ``start`` / ``end`` – "HH:MM" strings.  Overnight windows (start > end) are
    handled correctly (the window wraps past midnight).
    ``logic`` – ``"allow"`` or ``"block"``.
    """

    days: List[int] = field(default_factory=list)
    start: str = "00:00"
    end: str = "23:59"
    logic: str = "allow"

    def to_dict(self) -> Dict[str, Any]:
        day_names = [_WEEKDAY_INTS.get(d, d) if isinstance(d, int) else d for d in self.days]
        return {"days": day_names, "start": self.start, "end": self.end, "action": self.logic}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManualRule":
        raw_days = list(data.get("days") or [])
        days = [WEEKDAY_NAMES.get(d, d) if isinstance(d, str) else int(d) for d in raw_days]
        return cls(
            days=days,
            start=str(data.get("start") or "00:00"),
            end=str(data.get("end") or "23:59"),
            logic=str(data.get("action") or data.get("logic") or "allow"),
        )


@dataclass
class PriceConfig:
    """Electricity-price schedule configuration."""

    provider: str = ""  # "energy_charts" | "entsoe" | ""
    api_key: str = ""  # Only used for ENTSO-E
    bidding_zone: str = ""  # e.g. "ES", "DE-LU"
    strategy: str = "threshold"  # "threshold" | "cheapest_n"
    threshold_eur_mwh: float = 0.0
    cheapest_hours: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "entsoe_api_key": self.api_key,
            "bidding_zone": self.bidding_zone,
            "strategy": self.strategy,
            "threshold": self.threshold_eur_mwh,
            "cheapest_hours": self.cheapest_hours,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PriceConfig":
        return cls(
            provider=str(data.get("provider") or ""),
            api_key=str(data.get("entsoe_api_key") or data.get("api_key") or ""),
            bidding_zone=str(data.get("bidding_zone") or ""),
            strategy=str(data.get("strategy") or "threshold"),
            threshold_eur_mwh=float(data.get("threshold") or data.get("threshold_eur_mwh") or 0),
            cheapest_hours=int(data.get("cheapest_hours") or 0),
        )


@dataclass
class ScheduleConfig:
    """Top-level scheduling configuration persisted in the database."""

    enabled: bool = False
    mode: str = "manual"  # "manual" | "price" | "both"
    priority: str = "both_must_allow"  # "manual_first" | "price_first" | "both_must_allow"
    pause_behavior: str = "block_new"  # "block_new" | "pause_running"
    manual_rules: List[ManualRule] = field(default_factory=list)
    price: PriceConfig = field(default_factory=PriceConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "priority": self.priority,
            "pause_behavior": self.pause_behavior,
            "manual_rules": [r.to_dict() for r in self.manual_rules],
            "price": self.price.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleConfig":
        rules_raw = data.get("manual_rules") or []
        rules = [ManualRule.from_dict(r) for r in rules_raw] if isinstance(rules_raw, list) else []
        price_raw = data.get("price") or {}
        price = PriceConfig.from_dict(price_raw) if isinstance(price_raw, dict) else PriceConfig()
        return cls(
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode") or "manual"),
            priority=str(data.get("priority") or "both_must_allow"),
            pause_behavior=str(data.get("pause_behavior") or "block_new"),
            manual_rules=rules,
            price=price,
        )


# ── Price fetching ──────────────────────────────────────────────────────────

# Hourly prices keyed by ISO-date-hour string ("2026-04-09T14") → €/MWh.
HourlyPrices = Dict[str, float]

# Cache entry: (fetched_at_monotonic, date_string, prices_dict).
_PriceCacheEntry = Tuple[float, str, HourlyPrices]

_PRICE_CACHE_TTL = 6 * 3600  # refreshed every 6 h


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


def fetch_energy_charts_prices(bidding_zone: str, date_str: str) -> HourlyPrices:
    """Fetch day-ahead prices from Energy-Charts (Fraunhofer ISE).

    ``date_str`` – ``"YYYY-MM-DD"`` in local time of the requested zone.
    Returns a dict mapping ``"YYYY-MM-DDTHH"`` → price in €/MWh.
    """
    url = f"https://api.energy-charts.info/price?bzn={bidding_zone}&start={date_str}&end={date_str}"
    req = urlrequest.Request(url, headers={"Accept": "application/json", "User-Agent": "clutch-scheduler/1.0"})
    ctx = _build_ssl_context()
    with urlrequest.urlopen(req, timeout=20, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    # Energy-Charts returns {"unix_seconds": [...], "price": [...], ...}
    unix_seconds = body.get("unix_seconds") or []
    prices = body.get("price") or []
    result: HourlyPrices = {}
    for ts, price in zip(unix_seconds, prices):
        if price is None:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        key = dt.strftime("%Y-%m-%dT%H")
        result[key] = float(price)
    return result


def _find_entsoe_eic(bidding_zone: str) -> str:
    for zone in BIDDING_ZONES:
        if zone["code"] == bidding_zone:
            return zone["entsoe_eic"]
    return ""


def fetch_entsoe_prices(api_key: str, bidding_zone: str, date_str: str) -> HourlyPrices:
    """Fetch day-ahead prices from the ENTSO-E Transparency Platform.

    Requires a personal API security token (free registration at
    https://transparency.entsoe.eu/).
    """
    eic = _find_entsoe_eic(bidding_zone)
    if not eic:
        raise ValueError(f"Unknown bidding zone for ENTSO-E: {bidding_zone}")

    # Request period: full day in UTC
    period_start = f"{date_str.replace('-', '')}0000"
    period_end_date = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    period_end = period_end_date.strftime("%Y%m%d") + "0000"

    url = (
        "https://web-api.tp.entsoe.eu/api"
        f"?securityToken={api_key}"
        f"&documentType=A44"
        f"&in_Domain={eic}"
        f"&out_Domain={eic}"
        f"&periodStart={period_start}"
        f"&periodEnd={period_end}"
    )
    req = urlrequest.Request(url, headers={"User-Agent": "clutch-scheduler/1.0"})
    ctx = _build_ssl_context()
    with urlrequest.urlopen(req, timeout=30, context=ctx) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    ns = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
    result: HourlyPrices = {}
    for ts in root.findall(".//ns:TimeSeries", ns):
        period = ts.find("ns:Period", ns)
        if period is None:
            continue
        start_el = period.find("ns:timeInterval/ns:start", ns)
        if start_el is None or not start_el.text:
            continue
        base_dt = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
        for point in period.findall("ns:Point", ns):
            pos_el = point.find("ns:position", ns)
            price_el = point.find("ns:price.amount", ns)
            if pos_el is None or price_el is None or pos_el.text is None or price_el.text is None:
                continue
            position = int(pos_el.text) - 1  # 1-indexed
            dt = base_dt + timedelta(hours=position)
            key = dt.strftime("%Y-%m-%dT%H")
            result[key] = float(price_el.text)
    return result


def fetch_ree_pvpc_prices(date_str: str) -> HourlyPrices:
    """Fetch PVPC retail prices from REE (Red Eléctrica de España).

    The PVPC (Precio Voluntario para el Pequeño Consumidor) includes tolls,
    charges, taxes and VAT — the real consumer price in Spain.

    ``date_str`` – ``"YYYY-MM-DD"``.
    Returns a dict mapping ``"YYYY-MM-DDTHH"`` → price in €/MWh.
    No API key required.
    """
    start = f"{date_str}T00:00"
    end = f"{date_str}T23:59"
    url = (
        "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
        f"?start_date={start}&end_date={end}&time_trunc=hour"
    )
    req = urlrequest.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "clutch-scheduler/1.0",
    })
    ctx = _build_ssl_context()
    with urlrequest.urlopen(req, timeout=20, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    # Find the PVPC indicator (id "1001") inside the "included" array.
    result: HourlyPrices = {}
    for indicator in body.get("included") or []:
        if indicator.get("id") != "1001":
            continue
        for entry in (indicator.get("attributes") or {}).get("values") or []:
            value = entry.get("value")
            dt_str = entry.get("datetime")
            if value is None or dt_str is None:
                continue
            # Datetime comes as "2026-04-09T14:00:00.000+02:00"; parse to UTC key.
            dt = datetime.fromisoformat(dt_str)
            key = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
            result[key] = float(value)
        break
    return result


# ── Schedule engine ─────────────────────────────────────────────────────────


def _parse_time(s: str) -> Tuple[int, int]:
    """Parse ``"HH:MM"`` into ``(hour, minute)``."""
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _time_in_window(now_h: int, now_m: int, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    """Return ``True`` when ``now`` falls inside the window ``[start, end]``.

    Handles overnight windows (e.g. 22:00–08:00) correctly.
    """
    now_val = now_h * 60 + now_m
    start_val = start_h * 60 + start_m
    end_val = end_h * 60 + end_m

    if start_val <= end_val:
        return start_val <= now_val <= end_val
    # Overnight: window wraps past midnight
    return now_val >= start_val or now_val <= end_val


def parse_schedule_rule(text: str, logic: str = "allow") -> ManualRule:
    """Parse a CLI schedule string like ``"mon-fri 22:00-08:00"`` into a ``ManualRule``.

    Accepted formats:
    * ``"22:00-08:00"`` – every day
    * ``"mon-fri 00:00-08:00"`` – weekday range + time range
    * ``"sat,sun 00:00-23:59"`` – comma-separated days + time range
    """
    text = text.strip().lower()
    parts = text.split()

    days: List[int] = []
    time_part = text

    if len(parts) == 2:
        day_part, time_part = parts
        if "-" in day_part and ":" not in day_part:
            start_day, end_day = day_part.split("-", 1)
            s = WEEKDAY_NAMES.get(start_day[:3])
            e = WEEKDAY_NAMES.get(end_day[:3])
            if s is not None and e is not None:
                if s <= e:
                    days = list(range(s, e + 1))
                else:
                    days = list(range(s, 7)) + list(range(0, e + 1))
        else:
            for token in day_part.split(","):
                d = WEEKDAY_NAMES.get(token.strip()[:3])
                if d is not None:
                    days.append(d)

    if "-" in time_part and ":" in time_part:
        start_str, end_str = time_part.split("-", 1)
    else:
        start_str, end_str = "00:00", "23:59"

    return ManualRule(days=sorted(set(days)), start=start_str, end=end_str, logic=logic)


class ScheduleEngine:
    """Evaluates whether conversions are currently allowed."""

    def __init__(self, config: Optional[ScheduleConfig] = None):
        self._config = config or ScheduleConfig()
        self._lock = threading.Lock()

        # Price cache (in-memory, refreshed every 6 h or when config changes)
        self._price_cache: Optional[_PriceCacheEntry] = None
        self._price_fetch_lock = threading.Lock()
        self._last_price_error: str = ""

    @property
    def config(self) -> ScheduleConfig:
        with self._lock:
            return self._config

    def update_config(self, config: ScheduleConfig) -> None:
        with self._lock:
            self._config = config
        # Invalidate price cache when zone/provider changes
        self._price_cache = None

    # ── Manual evaluation ───────────────────────────────────────────────

    def _check_manual(self, now: datetime) -> Optional[bool]:
        """Evaluate manual rules at ``now``.

        Returns ``True`` (allowed), ``False`` (blocked), or ``None`` (no opinion).
        """
        cfg = self.config
        rules = cfg.manual_rules
        if not rules:
            return None

        weekday = now.weekday()
        h, m = now.hour, now.minute

        # Evaluate each rule; the last matching rule wins.
        result: Optional[bool] = None
        for rule in rules:
            if rule.days and weekday not in rule.days:
                continue
            sh, sm = _parse_time(rule.start)
            eh, em = _parse_time(rule.end)
            if not _time_in_window(h, m, sh, sm, eh, em):
                continue
            # Rule matches current time
            result = rule.logic == "allow"

        return result

    # ── Price evaluation ────────────────────────────────────────────────

    def _get_cached_prices(self) -> Optional[HourlyPrices]:
        entry = self._price_cache
        if entry is None:
            return None
        fetched_at, _date_str, prices = entry
        if time.monotonic() - fetched_at > _PRICE_CACHE_TTL:
            return None
        return prices

    def fetch_prices(self, *, force: bool = False) -> Optional[HourlyPrices]:
        """Fetch (or return cached) day-ahead prices.  Thread-safe."""
        if not force:
            cached = self._get_cached_prices()
            if cached is not None:
                return cached

        cfg = self.config
        pc = cfg.price
        if not pc.provider:
            return None
        if pc.provider != "ree_pvpc" and not pc.bidding_zone:
            return None

        with self._price_fetch_lock:
            # Double-check after acquiring lock
            if not force:
                cached = self._get_cached_prices()
                if cached is not None:
                    return cached

            today = datetime.now().strftime("%Y-%m-%d")
            try:
                if pc.provider == "energy_charts":
                    prices = fetch_energy_charts_prices(pc.bidding_zone, today)
                elif pc.provider == "entsoe":
                    if not pc.api_key:
                        self._last_price_error = "ENTSO-E API key is required."
                        return None
                    prices = fetch_entsoe_prices(pc.api_key, pc.bidding_zone, today)
                elif pc.provider == "ree_pvpc":
                    prices = fetch_ree_pvpc_prices(today)
                else:
                    self._last_price_error = f"Unknown price provider: {pc.provider}"
                    return None
            except Exception as exc:
                self._last_price_error = str(exc)
                log.warning("Price fetch failed for %s/%s: %s", pc.provider, pc.bidding_zone, exc)
                return None

            self._last_price_error = ""
            self._price_cache = (time.monotonic(), today, prices)
            return prices

    def _check_price(self, now: datetime) -> Optional[bool]:
        """Evaluate electricity-price rules at ``now``.

        Returns ``True`` (allowed), ``False`` (blocked), or ``None`` (no data / not configured).
        """
        cfg = self.config
        pc = cfg.price
        if not pc.provider:
            return None
        if pc.provider != "ree_pvpc" and not pc.bidding_zone:
            return None

        prices = self.fetch_prices()
        if not prices:
            # Graceful degradation: if no prices available, don't block
            return None

        now_utc = now.astimezone(timezone.utc)
        current_key = now_utc.strftime("%Y-%m-%dT%H")
        current_price = prices.get(current_key)

        if pc.strategy == "threshold":
            if pc.threshold_eur_mwh <= 0:
                return None
            if current_price is None:
                return None
            return current_price <= pc.threshold_eur_mwh

        if pc.strategy == "cheapest_n":
            if pc.cheapest_hours <= 0:
                return None
            # Determine today's cheapest N hours
            today_prefix = now_utc.strftime("%Y-%m-%dT")
            today_prices = {k: v for k, v in prices.items() if k.startswith(today_prefix)}
            if not today_prices:
                return None
            sorted_hours = sorted(today_prices.items(), key=lambda item: item[1])
            cheapest_keys = {k for k, _v in sorted_hours[: pc.cheapest_hours]}
            return current_key in cheapest_keys

        return None

    # ── Combined evaluation ─────────────────────────────────────────────

    def is_conversion_allowed(self) -> bool:
        """Return ``True`` if conversions should run right now."""
        cfg = self.config
        if not cfg.enabled:
            return True

        now = datetime.now().astimezone()

        manual_result: Optional[bool] = None
        price_result: Optional[bool] = None

        if cfg.mode in ("manual", "both"):
            manual_result = self._check_manual(now)
        if cfg.mode in ("price", "both"):
            price_result = self._check_price(now)

        return self._combine_results(manual_result, price_result, cfg.priority)

    @staticmethod
    def _combine_results(
        manual: Optional[bool], price: Optional[bool], priority: str
    ) -> bool:
        """Combine manual + price verdicts according to the configured priority."""
        if priority == "manual_first":
            if manual is not None:
                return manual
            if price is not None:
                return price
            return True

        if priority == "price_first":
            if price is not None:
                return price
            if manual is not None:
                return manual
            return True

        # "both_must_allow" (default)
        if manual is not None and not manual:
            return False
        if price is not None and not price:
            return False
        # If both are None, or all present values are True → allowed
        return True

    # ── Status for the API / dashboard ──────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current schedule status for the ``/config`` or ``/schedule`` endpoint."""
        cfg = self.config
        now = datetime.now().astimezone()
        allowed = self.is_conversion_allowed()

        status: Dict[str, Any] = {
            "enabled": cfg.enabled,
            "allowed": allowed,
            "mode": cfg.mode,
            "priority": cfg.priority,
            "pause_behavior": cfg.pause_behavior,
        }

        if cfg.mode in ("manual", "both"):
            manual_verdict = self._check_manual(now)
            status["manual_allowed"] = manual_verdict if manual_verdict is not None else True

        if cfg.mode in ("price", "both"):
            now_utc = now.astimezone(timezone.utc)
            current_key = now_utc.strftime("%Y-%m-%dT%H")
            prices = self._get_cached_prices()
            current_price = prices.get(current_key) if prices else None
            price_verdict = self._check_price(now)
            status["price_allowed"] = price_verdict if price_verdict is not None else True
            status["current_price_eur_mwh"] = current_price
            status["price_error"] = self._last_price_error or ""

        return status

    def get_cached_prices_list(self) -> List[Dict[str, Any]]:
        """Return cached day-ahead prices as a list for the dashboard chart."""
        prices = self._get_cached_prices()
        if not prices:
            return []
        result = []
        for key, price in sorted(prices.items()):
            try:
                dt = datetime.strptime(key, "%Y-%m-%dT%H")
                start_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
                result.append({"start": start_ts, "end": start_ts + 3600, "price": price})
            except (ValueError, TypeError):
                continue
        return result
