"""Calendar bins for first/last-date maps: weekly, thirds, halves, or custom boundaries.

Map values are day offsets from the season start (reference year 2001/2002, non-leap). A pixel's date is the offset
rounded to a whole day, so bin edges sit half a day below the first day of each bin (edge = offset - 0.5).
Each bin gets exactly one color and one legend label.

  weekly  days 1-6, 7-13, 14-20, 21-end      (last bin is longer in most months)
  thirds  days 1..n//3, ..., 21-end          (Early / Mid / Late)
  half    days 1-15, 16-end                  (1st half / 2nd half)
  custom  user-supplied bin start dates; values before the first start get a leading "Before ..." bin
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

MODES = ("auto", "weekly", "thirds", "half", "custom")
MODE_LABELS = {"auto": "Automatic", "weekly": "Weekly", "thirds": "Thirds (early / mid / late)",
               "half": "Halves", "custom": "Custom"}
MONTHS = [calendar.month_abbr[i] for i in range(1, 13)]


@dataclass
class Bins:
    edges: list[float]   # len n+1, ascending, in map-value (offset) space
    labels: list[str]    # len n

    def __len__(self):
        return len(self.labels)


def month_bin_starts(mode: str, n_days: int) -> list[int]:
    """1-based day-of-month where each bin begins."""
    if mode == "weekly":
        return [1, 7, 14, 21]
    if mode == "thirds":
        return [1, 1 + n_days // 3, 1 + (2 * n_days) // 3]
    if mode == "half":
        return [1, 1 + n_days // 2]
    raise ValueError(f"no fixed bins for mode '{mode}'")


def _label(mode: str, abbr: str, idx: int, s: int, e: int) -> str:
    if mode == "weekly":
        return f"{abbr} {s}–{e}"
    if mode == "thirds":
        return f"{('Early', 'Mid', 'Late')[idx]} {abbr} ({s}–{e})"
    return f"{('1st half', '2nd half')[idx]} {abbr} ({s}–{e})"


def _offset(d: dt.date, ref: dt.date) -> int:
    return (d - ref).days


def _fmt(d: dt.date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}"


def calendar_bins(mode: str, vmin: float, vmax: float, ref_month: int, ref_day: int) -> Bins:
    """Weekly / thirds / half bins covering every day from round(vmin) to round(vmax)."""
    if mode not in ("weekly", "thirds", "half"):
        raise ValueError(f"calendar_bins handles weekly/thirds/half, not '{mode}'")
    if not (vmin == vmin and vmax == vmax):
        raise ValueError("no data range to bin")
    ref = dt.date(2001, ref_month, ref_day)
    d_lo, d_hi = ref + dt.timedelta(days=round(vmin)), ref + dt.timedelta(days=round(vmax))
    edges: list[float] = []
    labels: list[str] = []
    y, m = d_lo.year, d_lo.month
    while (y, m) <= (d_hi.year, d_hi.month):
        n = calendar.monthrange(y, m)[1]
        starts = month_bin_starts(mode, n)
        for i, s in enumerate(starts):
            e = (starts[i + 1] - 1) if i + 1 < len(starts) else n
            b0, b1 = dt.date(y, m, s), dt.date(y, m, e)
            if b1 < d_lo or b0 > d_hi:
                continue
            if not edges:
                edges.append(_offset(b0, ref) - 0.5)
            edges.append(_offset(b1, ref) + 0.5)
            labels.append(_label(mode, MONTHS[m - 1], i, s, e))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return Bins(edges, labels)


_MD = re.compile(r"^\s*(?:(?P<mon>[A-Za-z]{3,9})\.?\s*(?P<d1>\d{1,2})|(?P<m2>\d{1,2})\s*[/-]\s*(?P<d2>\d{1,2}))\s*$")


def parse_month_day(text: str) -> tuple[int, int]:
    """'Oct 8', 'october 8', '10/8', '10-08' -> (10, 8)."""
    m = _MD.match(text)
    if not m:
        raise ValueError(f"can't read '{text.strip()}' as a date; use forms like 'Oct 8' or '10/8'")
    if m.group("mon"):
        word = m.group("mon").lower()
        names = {calendar.month_name[i].lower(): i for i in range(1, 13)} | {calendar.month_abbr[i].lower(): i for i in range(1, 13)}
        names["sept"] = 9
        if word not in names:
            raise ValueError(f"'{m.group('mon')}' isn't a month name in '{text.strip()}'")
        mo, d = names[word], int(m.group("d1"))
    else:
        mo, d = int(m.group("m2")), int(m.group("d2"))
    try:
        dt.date(2001, mo, d)
    except ValueError:
        raise ValueError(f"'{text.strip()}' is not a valid calendar date") from None
    return mo, d


def parse_custom_starts(text: str) -> list[tuple[int, int]]:
    parts = [p for p in re.split(r"[,;\n]+", text) if p.strip()]
    return [parse_month_day(p) for p in parts]


def custom_bins(starts: list[tuple[int, int]], vmin: float, vmax: float, ref_month: int, ref_day: int) -> Bins:
    """Bins that begin on each given month/day (in season order) and run to the day before the next start.
    Data before the first start gets a leading 'Before ...' bin and data after the last start extends that last bin,
    so every pixel is colored."""
    if not starts:
        raise ValueError("enter at least one bin start date")
    ref = dt.date(2001, ref_month, ref_day)
    offs: list[int] = []
    for mo, d in starts:
        date = dt.date(2001 if (mo, d) >= (ref_month, ref_day) else 2002, mo, d)
        offs.append(_offset(date, ref))
    if offs != sorted(set(offs)):
        raise ValueError("bin start dates must be in season order with no repeats "
                         f"(the season starts {_fmt(ref)})")
    lo, hi = round(vmin), round(vmax)
    date_of = lambda o: ref + dt.timedelta(days=o)
    edges: list[float] = []
    labels: list[str] = []
    if lo < offs[0]:
        edges.append(lo - 0.5)
        labels.append(f"Before {_fmt(date_of(offs[0]))}")
        edges.append(offs[0] - 0.5)
    else:
        edges.append(offs[0] - 0.5)
    for i, o in enumerate(offs):
        last = i == len(offs) - 1
        end = max(hi, o) if last else offs[i + 1] - 1
        edges.append(end + 0.5)
        if last:
            labels.append(f"{_fmt(date_of(o))} and later" if hi > o else _fmt(date_of(o)))
        else:
            e_date = date_of(end)
            labels.append(f"{_fmt(date_of(o))}–{e_date.day if e_date.month == date_of(o).month else _fmt(e_date)}"
                          if end > o else _fmt(date_of(o)))
    return Bins(edges, labels)
