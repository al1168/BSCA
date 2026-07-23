# Morning/Afternoon Distribution Bands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in setting that steers ~N% of members' Time-In into a morning band (earliest Time-In .. earliest + configurable length) and the rest later, per-member, deterministic across runs, with manual per-member pinning — never overriding schedule validity.

**Architecture:** A `band_for_member()` helper in `monthly_schedule/rules.py` hashes each `center_id` against a configured percentage (pins win over the hash; feature-off returns None). `build_rows` computes the band once per member and passes it to `build_daily_schedule`, which narrows the Time-In draw interval to the band *only when it fits inside the already-valid placement window* — otherwise it silently uses the full window. Five new `schedule_rules` keys flow through the existing GUI-settings → overrides merge; the debug CSV gains a `band` column.

**Tech Stack:** Python 3.11, pytest, PyQt6 (Settings dialog). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-23-morning-afternoon-bands-design.md`

**Test command** (run from repo root `c:\Users\luald\OneDrive\Desktop\BSCA`, project venv):
`python -m pytest <file> -v`

---

## File map

| File | Change |
|---|---|
| `monthly_schedule/rules.py` | 5 new default rule keys; new `band_for_member()` |
| `monthly_schedule/daily_schedule.py` | `build_daily_schedule(..., band=None)` narrows the Time-In draw |
| `monthly_schedule/rows.py` | `build_rows` passes the band; `build_debug_rows(..., center_id=None)` adds `band` column |
| `new_monthly_schedule.py` | `write_debug_csv` band column; `collect_debug_rows` passes center_id |
| `gui/app_settings.py` | 5 new keys in `DEFAULTS["schedule_rules"]` |
| `gui/settings_dialog.py` | checkbox + 4 fields, grey-out wiring, save-time validation, `parse_member_ids` helper |
| `gui/i18n.py` | 9 new keys × en/zh |
| `docs/scheduling-flow.md`, `docs/time-calculation-overview.md` | document the new rules |
| Tests | `tests/test_rules.py`, `tests/test_daily_schedule.py`, `tests/test_rows.py`, `tests/test_cli.py`, `tests/test_app_settings.py`, new `tests/test_settings_dialog.py` |

---

### Task 1: Rule keys + `band_for_member` (`monthly_schedule/rules.py`)

**Files:**
- Modify: `monthly_schedule/rules.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rules.py` (also add `band_for_member` to the existing `from monthly_schedule.rules import (...)` at the top):

```python
def test_band_defaults_present():
    d = SCHEDULE_RULES["Default"]
    assert d["band_enabled"] is False
    assert d["morning_percent"] == 80
    assert d["morning_window_min"] == 180
    assert d["morning_members"] == ()
    assert d["afternoon_members"] == ()


def _band_rules(**over):
    return {**SCHEDULE_RULES["Default"], "band_enabled": True, **over}


def test_band_disabled_returns_none_for_everyone():
    # band_enabled is False by default; pins are ignored while off.
    rules = {**SCHEDULE_RULES["Default"],
             "morning_members": (1,), "afternoon_members": (2,)}
    for cid in (1, 2, 3, 24010):
        assert band_for_member(cid, rules) is None


def test_band_missing_key_treated_as_disabled():
    # Settings files saved before this feature have no band_enabled key.
    rules = {k: v for k, v in SCHEDULE_RULES["Default"].items()
             if k != "band_enabled"}
    assert band_for_member(1, rules) is None


def test_band_none_center_id_returns_none():
    assert band_for_member(None, _band_rules()) is None


def test_band_deterministic_across_calls():
    rules = _band_rules()
    for cid in range(200):
        assert band_for_member(cid, rules) == band_for_member(cid, rules)


def test_band_distribution_near_percent():
    # Fixed IDs → deterministic result; md5 is uniform so 1000 IDs land
    # within a few points of 80/20 (expected 800, sd ~12.6).
    rules = _band_rules(morning_percent=80)
    morning = sum(
        band_for_member(cid, rules) == "morning" for cid in range(1000)
    )
    assert 750 <= morning <= 850


def test_band_percent_edges():
    ids = range(50)
    assert all(band_for_member(c, _band_rules(morning_percent=100))
               == "morning" for c in ids)
    assert all(band_for_member(c, _band_rules(morning_percent=0))
               == "afternoon" for c in ids)


def test_band_pins_win_over_hash():
    rules = _band_rules(morning_percent=100, afternoon_members=(7,))
    assert band_for_member(7, rules) == "afternoon"
    rules = _band_rules(morning_percent=0, morning_members=(7,))
    assert band_for_member(7, rules) == "morning"


def test_band_overlap_morning_wins():
    # GUI blocks this at save; defensively, morning wins.
    rules = _band_rules(morning_members=(7,), afternoon_members=(7,))
    assert band_for_member(7, rules) == "morning"


def test_band_ignores_junk_in_pin_lists():
    # Hand-edited settings file: string IDs are cast, junk is skipped.
    rules = _band_rules(morning_percent=0,
                        morning_members=("7", "junk", None))
    assert band_for_member(7, rules) == "morning"


def test_band_lists_survive_overrides_merge():
    # JSON overrides arrive as lists; get_rules_for_plan turns them into
    # tuples — membership checks must still work.
    rules = get_rules_for_plan("Default", {
        "band_enabled": True,
        "morning_members": [1, 2],
        "afternoon_members": [3],
    })
    assert band_for_member(1, rules) == "morning"
    assert band_for_member(3, rules) == "afternoon"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rules.py -v`
Expected: the new tests FAIL (ImportError on `band_for_member` / KeyError `band_enabled`); all pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `monthly_schedule/rules.py`, add `import hashlib` at the top of the file, add the five keys inside `SCHEDULE_RULES["Default"]` (after the `"dropoff_by_avail_end": True,` line):

```python
        # Morning/afternoon distribution (opt-in; spec 2026-07-23).
        # While band_enabled is falsy, Time-In placement is uniform,
        # exactly as before — pins and percentages are ignored.
        "band_enabled": False,
        "morning_percent": 80,       # % of members assigned morning
        "morning_window_min": 180,   # band length from earliest_time_in
        "morning_members": (),       # center_ids pinned morning
        "afternoon_members": (),     # center_ids pinned afternoon
```

and append the helper at the end of the file:

```python
def band_for_member(center_id, rules):
    """Return 'morning'/'afternoon' for this member, or None when the
    distribution feature is off (or center_id is unknown).

    Pins win over the hash; morning wins if an id is (defensively) in
    both lists. The md5 bucket is stable across runs and months, so a
    member keeps their band until the settings change. Non-integer
    entries in hand-edited pin lists are ignored.
    """
    if not rules.get("band_enabled") or center_id is None:
        return None
    try:
        member_id = int(center_id)
    except (TypeError, ValueError):
        return None

    def pinned(key):
        for raw in rules.get(key) or ():
            try:
                if int(raw) == member_id:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    if pinned("morning_members"):
        return "morning"
    if pinned("afternoon_members"):
        return "afternoon"
    digest = hashlib.md5(str(member_id).encode("ascii")).hexdigest()
    bucket = int(digest, 16) % 100
    if bucket < rules.get("morning_percent", 80):
        return "morning"
    return "afternoon"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rules.py tests/test_rules.py
git commit -m "feat(rules): band_for_member + morning/afternoon band defaults"
```

---

### Task 2: GUI settings defaults (`gui/app_settings.py`)

**Files:**
- Modify: `gui/app_settings.py`
- Test: `tests/test_app_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app_settings.py`:

```python
def test_band_defaults_on_fresh_install(settings_file):
    from gui import app_settings
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is False
    assert rules["morning_percent"] == 80
    assert rules["morning_window_min"] == 180
    assert rules["morning_members"] == []
    assert rules["afternoon_members"] == []


def test_band_keys_missing_filled_off(settings_file):
    # A settings file saved before this feature has no band keys — the
    # loader fills them from DEFAULTS with the feature OFF.
    settings_file.write_text(json.dumps({
        "schedule_rules": {"earliest_time_in": "09:00"}
    }))
    from gui import app_settings
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is False
    assert rules["earliest_time_in"] == "09:00"


def test_band_settings_round_trip(settings_file):
    from gui import app_settings
    s = app_settings.load()
    s["schedule_rules"]["band_enabled"] = True
    s["schedule_rules"]["morning_percent"] = 65
    s["schedule_rules"]["morning_window_min"] = 120
    s["schedule_rules"]["morning_members"] = [24010, 24011]
    s["schedule_rules"]["afternoon_members"] = [24012]
    app_settings.save(s)
    rules = app_settings.load()["schedule_rules"]
    assert rules["band_enabled"] is True
    assert rules["morning_percent"] == 65
    assert rules["morning_window_min"] == 120
    assert rules["morning_members"] == [24010, 24011]
    assert rules["afternoon_members"] == [24012]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app_settings.py -v`
Expected: the three new tests FAIL with KeyError `band_enabled` (the loader's known-key filter drops unknown keys, so round-trip also fails); existing tests PASS.

- [ ] **Step 3: Implement**

In `gui/app_settings.py`, add to `DEFAULTS["schedule_rules"]` after `"dropoff_by_avail_end": True,`:

```python
        "band_enabled": False,
        "morning_percent": 80,
        "morning_window_min": 180,
        "morning_members": [],
        "afternoon_members": [],
```

(Lists, not tuples — this dict round-trips through JSON; `get_rules_for_plan` converts to tuples at use site.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app_settings.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/app_settings.py tests/test_app_settings.py
git commit -m "feat(settings): morning/afternoon band keys in schedule_rules defaults"
```

---

### Task 3: Band-narrowed placement (`monthly_schedule/daily_schedule.py`)

**Files:**
- Modify: `monthly_schedule/daily_schedule.py`
- Test: `tests/test_daily_schedule.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_daily_schedule.py`. Default rules: earliest 08:00 + 180 min → cutoff 11:00 (660); Time-In can reach 12:30 (750).

```python
# Cutoff = 08:00 + 180 min = 11:00 (660 minutes).
BAND_RULES = {**SCHEDULE_RULES["Default"], "band_enabled": True}


def test_morning_band_caps_time_in():
    rng = random.Random(3)
    for _ in range(500):
        s = build_daily_schedule(BAND_RULES, rng, band="morning")
        assert _to_min(s["time_in"]) <= 660


def test_afternoon_band_floors_time_in():
    rng = random.Random(4)
    seen = []
    for _ in range(500):
        s = build_daily_schedule(BAND_RULES, rng, band="afternoon")
        ti = _to_min(s["time_in"])
        assert ti >= 660
        seen.append(ti)
    assert max(seen) > 660  # actually varies inside the band


def test_band_draws_still_satisfy_invariants():
    rng = random.Random(5)
    for band in ("morning", "afternoon"):
        for _ in range(200):
            s = build_daily_schedule(BAND_RULES, rng, band=band)
            ti, to = _to_min(s["time_in"]), _to_min(s["time_out"])
            assert ti >= 8 * 60
            assert to <= 16 * 60
            assert 210 <= to - ti <= 240


def test_afternoon_falls_back_when_window_is_morning_only():
    # Window 08:00-11:40: latest_in <= 08:10, entirely before the 11:00
    # cutoff → the afternoon band cannot fit. Validity wins: the full
    # window is used and the block still fits inside it.
    rng = random.Random(6)
    for _ in range(300):
        s = build_daily_schedule(BAND_RULES, rng,
                                 window=(480, 700), band="afternoon")
        assert _to_min(s["time_in"]) >= 480
        assert _to_min(s["time_out"]) <= 700


def test_morning_falls_back_when_window_starts_after_cutoff():
    # Window 12:00-16:00 starts after the 11:00 cutoff → morning band
    # empty → full window used.
    rng = random.Random(7)
    for _ in range(300):
        s = build_daily_schedule(BAND_RULES, rng,
                                 window=(720, 960), band="morning")
        assert _to_min(s["time_in"]) >= 720
        assert _to_min(s["time_out"]) <= 960


def test_band_none_works_with_legacy_rules_dict():
    # Callers with pre-feature rules dicts (no band keys) must not crash.
    legacy = {k: v for k, v in SCHEDULE_RULES["Default"].items()
              if k not in ("band_enabled", "morning_percent",
                           "morning_window_min", "morning_members",
                           "afternoon_members")}
    rng = random.Random(8)
    s = build_daily_schedule(legacy, rng)
    assert set(s) == {"pickup", "arrival", "time_in",
                      "time_out", "departure", "dropoff"}


def test_morning_band_with_snapping_stays_in_band():
    rules = {**BAND_RULES, "round_to_minutes": 5}
    rng = random.Random(9)
    for _ in range(300):
        s = build_daily_schedule(rules, rng, band="morning")
        ti = _to_min(s["time_in"])
        assert ti % 5 == 0
        assert ti <= 660
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daily_schedule.py -v`
Expected: new tests FAIL with `TypeError: build_daily_schedule() got an unexpected keyword argument 'band'`; existing tests PASS.

- [ ] **Step 3: Implement**

In `monthly_schedule/daily_schedule.py`, replace the signature and the Time-In placement block of `build_daily_schedule`:

```python
def build_daily_schedule(rules, rng, window=None, band=None):
```

Extend the docstring with:

```
    `band` (optional, 'morning'/'afternoon'/None) narrows WHERE inside
    the window Time-In is drawn (spec 2026-07-23): morning caps it at
    `earliest_time_in + morning_window_min`, afternoon floors it there.
    Validity always wins — when the band does not intersect the valid
    Time-In interval it is ignored for the day and the full interval is
    used. None = uniform placement, exactly the pre-feature behavior.
```

Replace these two lines:

```python
    latest_in = max(in_lo, out_hi - length)
    time_in = _round_to(rng.randint(in_lo, latest_in), step)
    # Snapping can nudge Time-In past the edges — clamp so it still fits.
    time_in = min(max(time_in, in_lo), latest_in)
```

with:

```python
    latest_in = max(in_lo, out_hi - length)
    # Morning/afternoon band: narrow the Time-In draw interval when the
    # band fits inside it; otherwise validity wins and the full interval
    # stays (the band is a soft preference, never an eligibility rule).
    eff_lo, eff_hi = in_lo, latest_in
    if band is not None:
        cutoff = (parse_hhmm(rules["earliest_time_in"])
                  + rules["morning_window_min"])
        if band == "morning":
            lo, hi = in_lo, min(latest_in, cutoff)
        else:
            lo, hi = max(in_lo, cutoff), latest_in
        if lo <= hi:
            eff_lo, eff_hi = lo, hi
    time_in = _round_to(rng.randint(eff_lo, eff_hi), step)
    # Snapping can nudge Time-In past the edges — clamp so it still fits.
    time_in = min(max(time_in, eff_lo), eff_hi)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_schedule.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/daily_schedule.py tests/test_daily_schedule.py
git commit -m "feat(daily): band-narrowed Time-In placement with validity-first fallback"
```

---

### Task 4: Wiring + debug band column (`monthly_schedule/rows.py`)

**Files:**
- Modify: `monthly_schedule/rows.py`
- Test: `tests/test_rows.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py`:

```python
# Band feature on; percent 100 → every hashed member is morning.
BAND_PLAN_RULES = {**PLAN_RULES,
                   "band_enabled": True,
                   "morning_percent": 100,
                   "morning_window_min": 180,
                   "morning_members": (),
                   "afternoon_members": ()}


def test_build_rows_applies_member_band():
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), BAND_PLAN_RULES,
                      random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert scheduled
    for r in scheduled:
        assert _to_min(r["time_in"]) <= 11 * 60   # 08:00 + 3h cutoff


def test_build_rows_honors_afternoon_pin():
    rules = {**BAND_PLAN_RULES, "afternoon_members": (1,)}
    rows = build_rows(2026, 5, _ctx_full_month("1,3,5"), rules,
                      random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert scheduled
    for r in scheduled:
        assert _to_min(r["time_in"]) >= 11 * 60


def test_build_rows_band_never_blocks_narrow_availability():
    # Afternoon-pinned member available only 08:00-11:40: every day must
    # still be scheduled (validity first), inside the availability.
    avail = [
        {"id": d, "center_id": 1,
         "effective_start_date": date(2026, 1, 1),
         "effective_end_date": None,
         "day_of_week": d, "avail_start": "08:00", "avail_end": "11:40"}
        for d in (1, 3, 5)
    ]
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1,3,5"}],
        absences=[], availabilities=avail, one_offs=[],
    )
    rules = {**BAND_PLAN_RULES, "afternoon_members": (1,)}
    rows = build_rows(2026, 5, ctx, rules, random.Random(0), center_id=1)
    scheduled = [r for r in rows if r["time_in"]]
    assert len(scheduled) == 13          # same Mon/Wed/Fri count as unbanded
    for r in scheduled:
        assert _to_min(r["time_in"]) >= _to_min("08:00")
        assert _to_min(r["time_out"]) <= _to_min("11:40")


def test_build_rows_legacy_rules_without_band_keys_still_work():
    rows = build_rows(2026, 5, _ctx_full_month(), PLAN_RULES,
                      random.Random(0), center_id=1)
    assert len(rows) == 31


def test_debug_rows_have_band_column():
    rows = build_debug_rows(2026, 5, _ctx_full_month("1"),
                            BAND_PLAN_RULES, center_id=1)
    assert rows
    assert all(r["band"] == "morning" for r in rows)


def test_debug_rows_band_blank_without_center_id():
    rows = build_debug_rows(2026, 5, _ctx_full_month("1"), PLAN_RULES)
    assert rows
    assert all(r["band"] == "" for r in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rows.py -v`
Expected: band tests FAIL (`time_in` past 11:00 for the first test, `TypeError` for the `center_id=` kwarg on `build_debug_rows`, KeyError `'band'`); existing tests PASS.

- [ ] **Step 3: Implement**

In `monthly_schedule/rows.py`:

1. Extend the rules import:

```python
from monthly_schedule.rules import parse_hhmm, format_minutes, band_for_member
```

2. In `build_rows`, before the `for day in ...` loop add:

```python
    band = band_for_member(center_id, plan_rules)
```

and pass it through in the generation call:

```python
                times = build_daily_schedule(
                    plan_rules, rng,
                    window=result.placement_window,
                    band=band,
                )
```

Add one line to the `build_rows` docstring: `Time-In placement honors the member's morning/afternoon band (band_for_member) when the feature is enabled; cached days are reused verbatim regardless of band.`

3. Change `build_debug_rows`'s signature and add the column:

```python
def build_debug_rows(year, month, ctx, plan_rules,
                     start_day=None, end_day=None, center_id=None):
```

At the top of the function body add:

```python
    band = band_for_member(center_id, plan_rules) or ""
```

and add to the appended row dict (after `"day": ...`):

```python
            "band": band,
```

Update the `build_debug_rows` docstring's field list to mention `band` ("morning"/"afternoon" on every row when the feature is on and a center_id was given; '' otherwise — band is a per-member property).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rows.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add monthly_schedule/rows.py tests/test_rows.py
git commit -m "feat(rows): apply member band in build_rows; band column in debug rows"
```

---

### Task 5: Debug CSV column (`new_monthly_schedule.py`)

**Files:**
- Modify: `new_monthly_schedule.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_write_debug_csv_includes_band_column(tmp_path):
    import new_monthly_schedule as cli
    from datetime import date
    rows = [{
        "center_id": 1, "name": "Doe, Jane", "date": date(2026, 5, 4),
        "day": "Mon", "scheduled": True, "reason": "",
        "reason_detail": "", "availability": "",
        "availability_source": "", "absent": "no", "auth_days": "1",
        "placement_window": "08:00-16:00", "max_length": "04:00",
        "band": "morning",
    }]
    path = tmp_path / "debug.csv"
    cli.write_debug_csv(rows, str(path))
    header, data = path.read_text(encoding="utf-8").strip().splitlines()
    assert header.split(",")[-1] == "band"
    assert data.split(",")[-1] == "morning"


def test_collect_debug_rows_carries_band(monkeypatch):
    import new_monthly_schedule as cli
    from datetime import date
    from monthly_schedule.eligibility_context import MemberContext

    member = {"center_id": 1, "first_name": "A", "last_name": "B",
              "health_plan": None}
    ctx = MemberContext(
        enrollments=[{"id": 1, "center_id": 1,
                      "start_date": date(2026, 1, 1), "end_date": None}],
        authorizations=[{"id": 1, "center_id": 1,
                         "auth_start": date(2026, 1, 1),
                         "auth_end": date(2026, 12, 31),
                         "effective_start": date(2026, 1, 1),
                         "effective_end": date(2026, 12, 31),
                         "auth_days": "1"}],
        absences=[], availabilities=[], one_offs=[],
    )
    rows = cli.collect_debug_rows(
        member, ctx, 2026, 5,
        schedule_rules_overrides={"band_enabled": True,
                                  "morning_percent": 100},
    )
    assert rows
    assert all(r["band"] == "morning" for r in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v -k band`
Expected: FAIL — header's last column is `max_length`, and `KeyError: 'band'` in `collect_debug_rows` (build_debug_rows got no center_id).

- [ ] **Step 3: Implement**

In `new_monthly_schedule.py`:

1. `write_debug_csv`: append `"band"` to the header list (after `"max_length"`) and `row["band"]` to the data `writerow` list (after `row["max_length"]`). Add `band` to the docstring's key list.

2. `collect_debug_rows`: pass the member's id through:

```python
        for r in build_debug_rows(
            year, month, ctx, rules, start_day, end_day,
            center_id=member["center_id"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: all PASS (including the pre-existing debug-CSV tests, which build their rows via `collect_debug_rows` and therefore now carry a `band` key).

- [ ] **Step 5: Commit**

```bash
git add new_monthly_schedule.py tests/test_cli.py
git commit -m "feat(debug): band column in the per-member debug CSV"
```

---

### Task 6: Settings dialog + i18n (`gui/settings_dialog.py`, `gui/i18n.py`)

**Files:**
- Modify: `gui/settings_dialog.py`, `gui/i18n.py`
- Create: `tests/test_settings_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_dialog.py` (tests the pure parsing helpers only — no QApplication needed):

```python
from gui.settings_dialog import parse_member_ids, _format_member_ids


def test_parse_member_ids_basic():
    assert parse_member_ids("24010, 24011,24012") == [24010, 24011, 24012]


def test_parse_member_ids_blank_is_empty():
    assert parse_member_ids("") == []
    assert parse_member_ids("   ") == []


def test_parse_member_ids_rejects_junk():
    assert parse_member_ids("24010, abc") is None
    assert parse_member_ids("12.5") is None


def test_format_member_ids_round_trip():
    ids = [24010, 24011]
    assert parse_member_ids(_format_member_ids(ids)) == ids
    assert _format_member_ids([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_dialog.py -v`
Expected: FAIL with ImportError (`parse_member_ids` does not exist).

- [ ] **Step 3: Implement the dialog changes**

In `gui/settings_dialog.py`:

1. Module-level helpers (next to `_hhmm`/`_qtime_to_minutes`):

```python
def _format_member_ids(ids) -> str:
    return ", ".join(str(i) for i in ids)


def parse_member_ids(text: str):
    """'24010, 24011' -> [24010, 24011]. Blank -> []. Returns None when
    any token is not an integer (caller warns and blocks the save)."""
    tokens = [t for t in text.replace(",", " ").split() if t]
    ids = []
    for t in tokens:
        try:
            ids.append(int(t))
        except ValueError:
            return None
    return ids
```

2. In `__init__`, after the `self._dropoff_deadline_check` rows block (before `layout.addWidget(self._rules_group)`):

```python
        self._band_enabled_check = QCheckBox()
        self._band_enabled_check.setChecked(
            bool(rules.get("band_enabled", False))
        )
        self._band_enabled_label = QLabel()
        rules_form.addRow(self._band_enabled_label,
                          self._band_enabled_check)

        self._morning_percent_spin = QSpinBox()
        self._morning_percent_spin.setRange(0, 100)
        self._morning_percent_spin.setValue(
            int(rules.get("morning_percent", 80))
        )
        self._morning_percent_spin.setFixedWidth(64)
        self._morning_percent_label = QLabel()
        rules_form.addRow(self._morning_percent_label,
                          self._morning_percent_spin)

        self._morning_window_edit = QTimeEdit()
        self._morning_window_edit.setDisplayFormat("HH:mm")
        self._morning_window_edit.setTime(
            _minutes_to_qtime(int(rules.get("morning_window_min", 180)))
        )
        self._morning_window_edit.setFixedWidth(82)
        self._morning_window_label = QLabel()
        rules_form.addRow(self._morning_window_label,
                          self._morning_window_edit)

        self._morning_ids_edit = QLineEdit(
            _format_member_ids(rules.get("morning_members") or [])
        )
        self._morning_ids_label = QLabel()
        rules_form.addRow(self._morning_ids_label, self._morning_ids_edit)

        self._afternoon_ids_edit = QLineEdit(
            _format_member_ids(rules.get("afternoon_members") or [])
        )
        self._afternoon_ids_label = QLabel()
        rules_form.addRow(self._afternoon_ids_label,
                          self._afternoon_ids_edit)

        # Grey out the band fields while the feature is off, so it's
        # obvious they have no effect.
        self._band_enabled_check.toggled.connect(self._update_band_enabled)
        self._update_band_enabled()
```

3. New method on `SettingsDialog`:

```python
    def _update_band_enabled(self):
        on = self._band_enabled_check.isChecked()
        for w in (self._morning_percent_spin, self._morning_window_edit,
                  self._morning_ids_edit, self._afternoon_ids_edit):
            w.setEnabled(on)
```

4. In `_retranslate`, after the `self._dropoff_deadline_label.setText(...)` call:

```python
        self._band_enabled_label.setText(tr("settings.rules.band_enabled"))
        self._morning_percent_label.setText(
            tr("settings.rules.morning_percent")
        )
        self._morning_window_label.setText(
            tr("settings.rules.morning_window")
        )
        self._morning_ids_label.setText(
            tr("settings.rules.morning_members")
        )
        self._afternoon_ids_label.setText(
            tr("settings.rules.afternoon_members")
        )
```

5. In `_save`, after the existing `if bad:` block returns, add band handling (validation only when the feature is on — a disabled feature never blocks saving):

```python
        band_enabled = self._band_enabled_check.isChecked()
        morning_ids = parse_member_ids(self._morning_ids_edit.text())
        afternoon_ids = parse_member_ids(self._afternoon_ids_edit.text())
        if band_enabled:
            if morning_ids is None or afternoon_ids is None:
                QMessageBox.warning(
                    self,
                    tr("settings.rules.band_invalid_ids.title"),
                    tr("settings.rules.band_invalid_ids.body"),
                )
                return
            overlap = sorted(set(morning_ids) & set(afternoon_ids))
            if overlap:
                QMessageBox.warning(
                    self,
                    tr("settings.rules.band_conflict.title"),
                    tr("settings.rules.band_conflict.body",
                       ids=", ".join(str(i) for i in overlap)),
                )
                return
        else:
            # Fields are disabled while off; keep whatever parses,
            # defensively dropping junk instead of blocking the save.
            morning_ids = morning_ids or []
            afternoon_ids = afternoon_ids or []
```

and extend the `"schedule_rules": {...}` result dict:

```python
                "band_enabled": band_enabled,
                "morning_percent": self._morning_percent_spin.value(),
                "morning_window_min":
                    _qtime_to_minutes(self._morning_window_edit.time()),
                "morning_members": morning_ids,
                "afternoon_members": afternoon_ids,
```

6. In `gui/i18n.py`, add to the **en** block (after `"settings.rules.dropoff_deadline"`):

```python
        "settings.rules.band_enabled": (
            "Morning/afternoon distribution:"
        ),
        "settings.rules.morning_percent": "Morning members (%):",
        "settings.rules.morning_window": (
            "Morning window length (HH:MM after earliest Time-In):"
        ),
        "settings.rules.morning_members": (
            "Always-morning member IDs (comma-separated):"
        ),
        "settings.rules.afternoon_members": (
            "Always-afternoon member IDs (comma-separated):"
        ),
        "settings.rules.band_invalid_ids.title": "Invalid Member IDs",
        "settings.rules.band_invalid_ids.body": (
            "Member ID lists must be numbers separated by commas "
            "(e.g. 24010, 24011)."
        ),
        "settings.rules.band_conflict.title": "Member In Both Lists",
        "settings.rules.band_conflict.body": (
            "These member IDs are in both the morning and afternoon "
            "lists: {ids}. Remove them from one list."
        ),
```

and the matching **zh** block (after `"settings.rules.dropoff_deadline"`):

```python
        "settings.rules.band_enabled": "上午/下午分布：",
        "settings.rules.morning_percent": "上午成员比例（%）：",
        "settings.rules.morning_window": (
            "上午时段长度（最早签到后的 时:分）："
        ),
        "settings.rules.morning_members": (
            "固定上午的成员 ID（逗号分隔）："
        ),
        "settings.rules.afternoon_members": (
            "固定下午的成员 ID（逗号分隔）："
        ),
        "settings.rules.band_invalid_ids.title": "成员 ID 无效",
        "settings.rules.band_invalid_ids.body": (
            "成员 ID 列表必须是用逗号分隔的数字（例如 24010, 24011）。"
        ),
        "settings.rules.band_conflict.title": "成员同时在两个列表中",
        "settings.rules.band_conflict.body": (
            "以下成员 ID 同时出现在上午和下午列表中：{ids}。"
            "请从其中一个列表中移除。"
        ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_dialog.py tests/test_i18n.py -v`
Expected: all PASS (`test_key_parity` proves en/zh key sets still match).

- [ ] **Step 5: Commit**

```bash
git add gui/settings_dialog.py gui/i18n.py tests/test_settings_dialog.py
git commit -m "feat(gui): morning/afternoon distribution settings with enable gate"
```

---

### Task 7: Docs, full suite, manual smoke

**Files:**
- Modify: `docs/scheduling-flow.md`, `docs/time-calculation-overview.md`

- [ ] **Step 1: Update the docs**

In `docs/time-calculation-overview.md`, add the five keys to the rules table with these descriptions (mirror the table's existing format):

- `band_enabled` — Morning/afternoon distribution master switch (off by default). Off = uniform Time-In placement.
- `morning_percent` — % of members assigned to the morning band (deterministic hash of center_id; pins excluded).
- `morning_window_min` — Morning band length in minutes from `earliest_time_in` (Time-In cutoff).
- `morning_members` / `afternoon_members` — center_ids pinned to a band, bypassing the hash.

Also add a short paragraph where Time-In placement is described: banding narrows *where inside the valid placement window* Time-In is drawn; it never changes the window, eligibility, or the drop-off deadline, and falls back to the full window when the band doesn't fit.

In `docs/scheduling-flow.md`, add a matching step/glossary entry: after the placement window is computed, `band_for_member` picks morning/afternoon (hash or pin) and `build_daily_schedule` prefers that band for Time-In, validity permitting.

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest`
Expected: all tests PASS.

- [ ] **Step 3: Manual smoke test of the dialog**

Run: `python gui.py` → Settings. Verify: the four band fields are greyed out until the checkbox is ticked; junk in an ID list blocks save with the warning only while enabled; save + reopen round-trips the values.

- [ ] **Step 4: Commit**

```bash
git add docs/scheduling-flow.md docs/time-calculation-overview.md
git commit -m "docs: morning/afternoon distribution bands"
```
