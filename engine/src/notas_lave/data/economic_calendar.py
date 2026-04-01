"""
Economic Calendar — high-impact news event schedule and blackout detection.

WHY NEWS BLACKOUT MATTERS:
- High-impact events (NFP, CPI, FOMC) cause 100-500 pip moves in SECONDS
- Spreads widen 5-10x during news (your 30-cent gold spread becomes $3)
- Stop losses get slipped — you might lose 3-5x what you planned
- Technical analysis is USELESS during news — price is driven by the data
- FundingPips REQUIRES no trading 5 min before/after news (funded accounts)

HOW THIS WORKS:
- Maintains a static schedule of known recurring high-impact events
- NFP = first Friday, CPI = ~13th, FOMC = 8 meetings/year, etc.
- Generates event dates programmatically (no hardcoded dates)
- is_in_blackout() checks if a given timestamp is within N minutes of an event
- Works for both LIVE (using current time) and BACKTESTING (using candle time)

IMPACT LEVELS:
- HIGH: NFP, CPI, FOMC, GDP — full blackout, no trading
- MEDIUM: Retail Sales, Jobless Claims — optional blackout
- LOW: Housing data, etc. — no blackout, just awareness
"""

import logging
from datetime import datetime, date, time, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo
import calendar

logger = logging.getLogger(__name__)

# RC-08/DE-11: Use proper timezone for US Eastern time.
# This auto-handles EST (UTC-5) vs EDT (UTC-4) transitions.
# Without this, blackout windows are wrong for 8 months of the year.
US_EASTERN = ZoneInfo("America/New_York")


class EventImpact(str, Enum):
    HIGH = "HIGH"       # Full blackout — never trade around these
    MEDIUM = "MEDIUM"   # Blackout recommended
    LOW = "LOW"         # No blackout, but be aware


@dataclass(frozen=True)
class EconomicEvent:
    """A single scheduled economic event."""
    name: str
    dt: datetime          # Event time in UTC
    impact: EventImpact
    currency: str         # Affected currency (USD, EUR, GBP, etc.)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "datetime": self.dt.isoformat(),
            "impact": self.impact.value,
            "currency": self.currency,
            "description": self.description,
        }


# --- Date generation helpers ---

def _first_friday(year: int, month: int) -> date:
    """First Friday of a given month. NFP is always released on this day."""
    cal = calendar.monthcalendar(year, month)
    # calendar.FRIDAY = 4 (Mon=0)
    for week in cal:
        if week[calendar.FRIDAY] != 0:
            return date(year, month, week[calendar.FRIDAY])
    return date(year, month, 1)  # Fallback


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Get the nth occurrence of a weekday in a month (1-indexed)."""
    cal = calendar.monthcalendar(year, month)
    count = 0
    for week in cal:
        if week[weekday] != 0:
            count += 1
            if count == n:
                return date(year, month, week[weekday])
    return date(year, month, 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Get the last occurrence of a weekday in a month."""
    cal = calendar.monthcalendar(year, month)
    for week in reversed(cal):
        if week[weekday] != 0:
            return date(year, month, week[weekday])
    return date(year, month, 1)


# --- FOMC meeting dates ---
# FOMC meets 8 times per year. Dates are published annually.
# These are approximate — the Fed publishes exact dates each December.
# Format: (month, day_range_start) — meetings are typically Tue-Wed
FOMC_MONTHS = [1, 3, 5, 6, 7, 9, 11, 12]


def _generate_fomc_dates(year: int) -> list[date]:
    """
    Generate approximate FOMC meeting dates for a year.
    FOMC typically meets on the 3rd or 4th Wednesday.
    The rate decision is announced at 2:00 PM EST on the 2nd day.
    """
    dates = []
    for month in FOMC_MONTHS:
        # FOMC usually meets on 3rd or 4th Wednesday
        try:
            d = _nth_weekday(year, month, calendar.WEDNESDAY, 3)
            dates.append(d)
        except Exception as e:
            logger.warning("Failed to generate FOMC date for month %d of %d: %s", month, year, e)
    return dates


# --- Main event generation ---

def generate_events(year: int, month: int) -> list[EconomicEvent]:
    """
    Generate all known high-impact economic events for a given month.

    Covers:
    - NFP (Non-Farm Payrolls): 1st Friday, 8:30 AM EST (13:30 UTC)
    - CPI (Consumer Price Index): ~13th, 8:30 AM EST
    - FOMC Rate Decision: if meeting this month, 2:00 PM EST (19:00 UTC)
    - GDP (Gross Domestic Product): last Thursday, 8:30 AM EST
    - Retail Sales: ~15th, 8:30 AM EST
    - Jobless Claims: every Thursday, 8:30 AM EST
    """
    events = []

    # RC-08/DE-11: Use proper US Eastern timezone for event times.
    # 8:30 AM Eastern and 2:00 PM Eastern in local time, then convert to UTC.
    # This automatically handles EST (UTC-5) vs EDT (UTC-4).
    def _to_utc(d: date, local_time: time) -> datetime:
        """Convert a date + US Eastern local time to UTC datetime."""
        local_dt = datetime.combine(d, local_time, tzinfo=US_EASTERN)
        return local_dt.astimezone(timezone.utc)

    eastern_830 = time(8, 30)   # 8:30 AM Eastern (local)
    eastern_1400 = time(14, 0)  # 2:00 PM Eastern (local)

    # NFP — First Friday of the month
    nfp_date = _first_friday(year, month)
    events.append(EconomicEvent(
        name="NFP (Non-Farm Payrolls)",
        dt=_to_utc(nfp_date, eastern_830),
        impact=EventImpact.HIGH,
        currency="USD",
        description="US employment report. Biggest market mover. Expect 50-200+ pip Gold moves.",
    ))

    # CPI — Usually around 13th of the month
    cpi_day = min(13, calendar.monthrange(year, month)[1])
    cpi_date = date(year, month, cpi_day)
    # If it falls on weekend, move to next Tuesday
    while cpi_date.weekday() >= 5:
        cpi_date += timedelta(days=1)
    events.append(EconomicEvent(
        name="CPI (Consumer Price Index)",
        dt=_to_utc(cpi_date, eastern_830),
        impact=EventImpact.HIGH,
        currency="USD",
        description="Inflation data. Directly impacts Fed rate expectations. 50-150 pip Gold moves.",
    ))

    # FOMC — Check if there's a meeting this month
    fomc_dates = _generate_fomc_dates(year)
    for fd in fomc_dates:
        if fd.month == month:
            events.append(EconomicEvent(
                name="FOMC Rate Decision",
                dt=_to_utc(fd, eastern_1400),
                impact=EventImpact.HIGH,
                currency="USD",
                description="Federal Reserve interest rate decision. Can move Gold 100-300 pips.",
            ))

    # GDP — Last Thursday of the month
    gdp_date = _last_weekday(year, month, calendar.THURSDAY)
    events.append(EconomicEvent(
        name="GDP (Gross Domestic Product)",
        dt=_to_utc(gdp_date, eastern_830),
        impact=EventImpact.HIGH,
        currency="USD",
        description="Economic growth report. Significant market impact on release.",
    ))

    # Retail Sales — Around 15th of the month
    rs_day = min(15, calendar.monthrange(year, month)[1])
    rs_date = date(year, month, rs_day)
    while rs_date.weekday() >= 5:
        rs_date += timedelta(days=1)
    events.append(EconomicEvent(
        name="Retail Sales",
        dt=_to_utc(rs_date, eastern_830),
        impact=EventImpact.MEDIUM,
        currency="USD",
        description="Consumer spending data. Moderate market impact.",
    ))

    # Jobless Claims — Every Thursday
    d = date(year, month, 1)
    while d.month == month:
        if d.weekday() == calendar.THURSDAY:
            events.append(EconomicEvent(
                name="Jobless Claims",
                dt=_to_utc(d, eastern_830),
                impact=EventImpact.MEDIUM,
                currency="USD",
                description="Weekly unemployment claims. Moderate impact unless surprising.",
            ))
        d += timedelta(days=1)

    return sorted(events, key=lambda e: e.dt)


def get_events_around(
    target_dt: datetime,
    window_days: int = 3,
) -> list[EconomicEvent]:
    """
    Get all events within ±window_days of a target datetime.
    Generates events for the relevant month(s).
    """
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)

    start = target_dt - timedelta(days=window_days)
    end = target_dt + timedelta(days=window_days)

    # Generate events for all months in the window
    events = []
    current = date(start.year, start.month, 1)
    end_date = date(end.year, end.month, 1)
    while current <= end_date:
        events.extend(generate_events(current.year, current.month))
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    # Filter to window
    return [e for e in events if start <= e.dt <= end]


def is_in_blackout(
    check_time: datetime,
    blackout_minutes: int = 5,
    min_impact: EventImpact = EventImpact.HIGH,
) -> tuple[bool, EconomicEvent | None]:
    """
    Check if a given time falls within a news blackout window.

    Args:
        check_time: The time to check (candle timestamp or current time)
        blackout_minutes: Minutes before AND after event to block (default 5)
        min_impact: Minimum impact level to trigger blackout (default HIGH only)

    Returns:
        (is_blocked, event_that_caused_block) or (False, None)

    This is the core function used by:
    - Risk manager: blocks trade validation
    - Scanner: skips sending alerts
    - Backtester: skips opening new trades
    """
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)

    # Only need events from today (±1 day for edge cases)
    events = get_events_around(check_time, window_days=1)

    impact_levels = {EventImpact.HIGH}
    if min_impact == EventImpact.MEDIUM:
        impact_levels.add(EventImpact.MEDIUM)
    elif min_impact == EventImpact.LOW:
        impact_levels.update({EventImpact.MEDIUM, EventImpact.LOW})

    blackout_window = timedelta(minutes=blackout_minutes)

    for event in events:
        if event.impact not in impact_levels:
            continue

        time_diff = abs((check_time - event.dt).total_seconds())
        if time_diff <= blackout_window.total_seconds():
            return True, event

    return False, None


def get_upcoming_events(
    from_time: datetime | None = None,
    limit: int = 10,
) -> list[EconomicEvent]:
    """
    Get the next N upcoming events from a given time.
    Used by the dashboard to show what's coming.
    """
    if from_time is None:
        from_time = datetime.now(timezone.utc)
    if from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)

    events = get_events_around(from_time, window_days=14)
    upcoming = [e for e in events if e.dt >= from_time]
    return upcoming[:limit]

