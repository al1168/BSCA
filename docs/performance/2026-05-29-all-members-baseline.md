# All Members Performance Baseline (2026-05-29)

**Workload:** 452-member run against `test_dbs/populate_real_members.accdb`
**Mocks:** travel resolution returns a constant (no Google calls). No Qt thread; loop body runs in plain Python.
**Hardware:** Windows 11, Python 3.13, Microsoft Access ODBC Driver
**Bench script:** `_bench_all.py` (gitignored)
**cProfile output:** `_bench_all.prof` (gitignored)

---

## TL;DR

> **`pyodbc.connect` is the bottleneck. Period.**
> Opening + closing an Access ODBC connection costs ~400 ms each time. We open 1,808 connections per run (452 members × 4 supporting-table queries). That's 12 minutes of connection-management overhead per run, against only ~6 seconds of actual SQL work.
>
> **The fix is structural, not micro:** stop opening a new connection per query. Either reuse one connection across the whole worker run, or — even better — eager-fetch all four supporting tables in 4 unfiltered queries (instead of 1,808 per-member queries) and index in Python. Estimated wall-clock savings: ~95% (from ~8 min down to ~25 s).

---

## Headline numbers

| Pass | Total | Successful workbooks | Eligibility failures |
| --- | --- | --- | --- |
| Cold | **505.3 s** (8m 25s) | 407 | 45 |
| Warm | 639.8 s (10m 40s)¹ | 407 | 45 |
| cProfile-instrumented² | 757.4 s (12m 37s) | 407 | 45 |

¹ Warm came in slower than cold this run, which sounds backwards. Two contributors: (1) cProfile's `pyodbc.connect` mean of 320 ms varies ±20–40 ms with system load, and at 1,808 calls that fluctuation alone explains ±60 s; (2) the cold pass was the first measurement after a fresh Python boot, before Windows started any background indexer activity that ran during the warm pass. Both passes show the same component breakdown, which is the actually-useful signal.
² The cProfile pass adds substantial overhead — used for hot-function ranking only, not for wall-clock judgment.

Peak Python heap (cold pass via `tracemalloc`): **4.0 MB**. Memory is not a concern at this scale.

---

## Component breakdown

### Cold pass (505.3 s)

| Group | Seconds | % total | Calls | Avg per call |
| --- | --- | --- | --- | --- |
| **`db.ctx_per_member`** (4 queries per member, each opens its own connection) | **480.95** | **95.2 %** | 452 | 1064.1 ms |
| `workbook.write` (openpyxl build + save) | 23.48 | 4.6 % | 407 | 57.7 ms |
| `rows.gen` (build_rows + build_daily_schedule) | 0.68 | 0.1 % | 407 | 1.7 ms |
| `db.contacts` (one `get_all_members` call) | 0.60 | 0.1 % | 1 | 597.9 ms |
| `eligibility.month_failure` | 0.05 | 0.0 % | 452 | 0.1 ms |
| Other (Python overhead, mkdir, etc.) | ~0 | ~0 % | — | — |

**95% of the wall-clock disappears into per-member DB queries.** Inside that bucket, `pyodbc.connect` is where 76% of total CPU time gets spent (next section).

### Warm pass (639.8 s)

Same shape, slightly worse absolute numbers (system noise):
- `db.ctx_per_member`: **628.93 s (98.3%)** — DB connection cost is constant regardless of OS file cache.
- `workbook.write`: **10.57 s (1.7%)** — clear win from OS file cache (down from 23.5 s).
- Everything else: negligible.

---

## cProfile top functions

### By total (own) time — where CPU actually spends cycles

| ncalls | tottime (s) | per call | cumtime (s) | Function |
| --- | --- | --- | --- | --- |
| **1808** | **577.86** | **0.320** | 577.89 | **`{built-in method pyodbc.connect}`** |
| **1808** | **150.70** | **0.083** | 150.70 | **`{method 'close' of 'pyodbc.Connection'}`** |
| 1808 | 6.14 | 0.003 | 6.14 | `{method 'execute' of 'pyodbc.Cursor'}` |
| 1628 | 3.96 | 0.002 | 4.05 | `{built-in method _io.open}` |
| 1.6 M / 588 K | 3.45 | — | 6.01 | `openpyxl serialisable.__hash__` |
| 11.7 M | 1.10 | — | 1.11 | `{built-in method builtins.isinstance}` |
| 9.7 M | 0.93 | — | 0.97 | `{built-in method builtins.getattr}` |
| 8.7 M | 0.90 | — | 0.90 | `{method 'append' of 'list'}` |

### By cumulative time — top of the call tree

| ncalls | tottime | cumtime (s) | Function |
| --- | --- | --- | --- |
| 1 | 0.03 | 757.39 | `_bench_all.run_one_pass` |
| 1808 | 0.04 | **734.97** | **`db._fetch_all`** — the wrapper that opens, executes, closes |
| 1808 | 577.86 | 577.89 | `pyodbc.connect` |
| 452 | — | 183.96 | `db.get_absences` |
| 452 | — | 183.85 | `db.get_availability` |
| 452 | — | 183.81 | `db.get_authorizations` |
| 452 | — | 183.36 | `db.get_enrollments` |
| 1808 | 150.70 | 150.70 | `pyodbc.Connection.close` |
| 407 | 0.01 | 21.76 | `monthly_schedule/workbook.build_workbook` |

**Read this together:** every call to `get_enrollments` (and the three siblings) is ~407 ms — and of that, ~320 ms is `pyodbc.connect`, ~83 ms is `connection.close`, and ~3 ms is the actual `cursor.execute`. **Connection setup/teardown is 99.3% of the per-call cost; the SQL itself is ~0.7%.**

---

## Bottleneck call-outs

### 1. `pyodbc.connect` — 76% of cProfile-instrumented runtime

[`monthly_schedule/db.py:_fetch_all`](../../monthly_schedule/db.py) opens a fresh `pyodbc.Connection` for every call. The same per-connection-open cost applies to every other top-level fetcher (`get_member`, `get_members_by_plan`, `get_all_members`, `get_enrollments`, …) — they each carry the boilerplate.

For All Members at 452 members:
- Per member: 4 supporting-table queries → 4 `connect()` + 4 `close()`
- Total: 1,808 connections per pass
- Per connection: ~320 ms open + ~83 ms close = ~400 ms of pure overhead
- Aggregate: **~725 seconds** burned on connection management. Not on the queries — on the *handshake*.

The Access ODBC driver is slow to attach because it has to mount the `.accdb` file each time (Access is a file-based DB, not a server). That cost is mostly fixed; the only way to reduce it is to amortize: open once, query many times.

### 2. `workbook.write` — 4.6% of total (cold)

openpyxl spends most of its time in `to_tree`, `serialisable.__hash__`, and `etree_write_cell`. At 26–58 ms per workbook this is acceptable for now; if connection overhead is fixed, workbook write becomes the dominant cost (warm-pass numbers project ~10 s for the whole batch).

There are minor wins possible (write-only mode, raising openpyxl's worksheet `write_only=True`, or using `XlsxWriter` which is consistently 2–3× faster for new-file writes), but those are second-order optimizations to consider *after* the DB layer is fixed.

### 3. Everything else — under 1%

`build_rows`, `compute_month_failure`, `MemberContext` lookups, and travel resolution (mocked) all rounded to noise. The per-day eligibility check at 0.1 ms × 31 days × 452 members = ~1.4 s total is negligible. No optimization warranted in these areas.

---

## Recommended optimizations (ranked by impact ÷ effort)

### 1. Eager-fetch all supporting tables (**recommended**) — projected ~95% wall-clock cut

Replace the 1,808 per-member queries with **4 unfiltered queries** to read the entire `Enrollment`, `Authorization`, `Absences`, and `Availability` tables in one shot, then index by `Center ID` in Python:

```python
def get_all_enrollments(db_path) -> dict[int, list[dict]]:
    """Return {center_id: [enrollment rows...]} for every row in the table."""
    # 1 connect, 1 execute, 1 close. ~400 ms total instead of ~452 * 400 ms.
```

Same shape for the other three. The worker then does `enrollments_idx[cid]` instead of `get_enrollments(cid, db_path)` — a dict lookup instead of an ODBC round-trip.

**Numbers:**
- Before: 1,808 connections × 400 ms ≈ 723 s
- After: 4 connections × 400 ms ≈ 1.6 s
- Saved: ~720 s
- Projected new total: ~25 s (workbook write at ~10 s + small Python overhead)

**Touch points:**
- New functions in `monthly_schedule/db.py`: `get_all_enrollments`, `get_all_authorizations`, `get_all_absences`, `get_all_availability` — each returning a `{center_id: [rows]}` dict.
- New worker mode-aware optimization in `gui/worker.py`: when `mode == "all"` (or any batch mode), pre-fetch once before the loop and build `MemberContext` from in-memory dicts.
- For single/multiple modes, keep the per-member calls — they're 1–10 members, not worth restructuring.

**Effort:** Small. ~50 lines of new code, no schema change, no architectural shift. Tests stay green because the per-member fetchers stay around for the single/multiple modes.

**Risks:** Loading every Enrollment row at once raises peak memory. At ~10 KB per row × thousands of rows = a few MB. Negligible.

### 2. Connection reuse fallback — projected ~75% wall-clock cut

If for some reason eager-fetch is too invasive (e.g., tables grow to millions of rows and memory becomes a concern), the simpler structural fix is **one open connection per worker run**. Open once at the top of `run()`, pass the cursor down through each fetcher, close at the end.

**Numbers:**
- Before: 1,808 × 400 ms ≈ 723 s
- After: 1 × 400 ms + 1,808 × 3 ms ≈ 5.8 s (1 connect + 1,808 executes — query time is preserved)
- Saved: ~717 s

This is a bigger refactor (every fetcher needs a `conn` parameter) and produces only a slightly worse outcome than option 1 because the per-`execute` time is unchanged. **Recommended only if option 1 is rejected.**

### 3. Workbook write — switch to `XlsxWriter` or openpyxl write-only mode

Currently 23.5 s cold / 10.6 s warm. After option 1, workbook becomes the dominant cost. Two paths:

- **openpyxl `write_only=True`** — minimal code change but loses some formatting flexibility. ~30% faster in practice.
- **Migrate to `XlsxWriter`** — bigger rewrite but consistently 2–3× faster for new-file writes. Two output paths to maintain if the existing test_workbook.py tests pin the openpyxl behavior.

Either is a 5–15 s saving on full-plan runs. Worth doing after option 1 lands, not before.

### 4. Parallelize workbook write across threads

After option 1, the loop becomes CPU-bound on openpyxl. Workbook writes are independent — they can run in a `ThreadPoolExecutor`. With 4 workers, the workbook phase could drop from 10 s to ~3 s. Combined with option 1, total run time approaches ~5 s for 452 members.

This is **optional polish** — only worth doing if the post-option-1 baseline is still too slow for someone's taste. The Python GIL doesn't get in the way because openpyxl spends much of its time in I/O / C extensions.

---

## Out of scope (deliberately not pursued)

- **Travel API parallelisation.** Mocked here. The real per-member Google Routes call is the actual bottleneck *in production*, but only because the cache is cold. Once `geo_cache.json` warms up over a few runs (TTL = 1 week), nearly all members hit the cache and the per-member network cost drops to ~0. The DB fetch problem identified above will dominate *both* cold and warm production runs.
- **Connection pooling via `pyodbc`'s built-in pooling flag.** Default is on but Access driver doesn't honor it cleanly (verified empirically by the 320 ms-per-connect baseline). Skip.
- **Per-day eligibility re-architecture.** At 0.1 ms × 13,612 day-checks = ~1.4 s total, the per-day logic is fast enough to leave alone.
- **Removing the `_NoPlan` folder creation overhead.** `os.makedirs(exist_ok=True)` is a free no-op when the dir exists; only the first 452-th member's plan code creates a new dir, and Windows fs operations at this scale are negligible.

---

## Reproducing this

```powershell
# Make sure the test DB exists (~30 seconds, copies prod + truncates + seeds)
python scripts\make_test_db.py --scenario populate_real_members

# Run the benchmark (8–13 minutes total: cold + warm + cProfile passes)
.venv\Scripts\python.exe _bench_all.py | Tee-Object _bench_all.txt
```

The bench script, raw output, and `.prof` file are all gitignored. Only this report lands in the repo.
