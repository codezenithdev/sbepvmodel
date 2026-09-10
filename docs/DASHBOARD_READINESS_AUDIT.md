# Dashboard End-User Readiness Audit

Status: **review only — no production code was changed**

Date: **2026-09-10**

Scope: **Can the dashboard be presented to end users, and what should change first**

Revision: **2026-09-10b — adds §4.0, a measured 2 GB capacity failure at 12 years**

Branch: `claude/dashboard-readiness-review-ipmxwm`

This document records an independent readiness review of the SB Energy PV
Operations Dashboard. It states what was actually executed and observed, what
blocks an end-user rollout, and a prioritized remediation list with file
references. Every measurement below was produced in this session; nothing is
carried over from documentation or prior reports.

Findings are ordered by the risk they carry into a rollout, not by effort.

---

## 1. Verdict

**Presentable, but not yet self-serve.**

The dashboard is visually and structurally ready to put in front of people. The
engineering underneath is disciplined: the full suite passes, lint and typecheck
are silent, there are no TODO markers or debug logging anywhere in the tracked
source, and the failure paths that matter for data integrity behave correctly.

Three things stand between the current state and an unattended end-user rollout:

1. **A 12-year annual selection exceeds the 2 GB instance and OOM-kills the
   whole service** — measured, not projected (§4.0). Every 12-year selection the
   API currently accepts is over the limit. This is the one item that can take
   the dashboard down for all users.
2. A user can queue a job that runs for hours, on a single shared worker thread,
   with no duration estimate and no queue position (§4.1).
3. Authentication is fail-open — an unset environment variable silently serves
   the dashboard, and the credentials it holds, to anyone (§4.2).

Recommended posture by audience:

| Audience | Ready? | Condition |
| --- | --- | --- |
| Demo to a small group, operator driving | **Yes, today** | Set the Basic-auth pair; keep to hourly interval and **8 years or fewer** |
| Named analysts, self-serve, supervised | **After §4.0, §4.2, §5.1, §5.2** | §4.0's admission guard is the gating item |
| Unattended multi-user rollout | **After §4.0's chunking fix and §6 is decided** | The shared-workspace model needs a product decision, not a patch |

**Hard operating limit until §4.0 is fixed: 8 years, hourly interval.** That
lands at roughly 74–77% of the 2 GB instance. Ten years is ~92% and should be
treated as unsafe; twelve years is over the limit.

---

## 2. What was executed

All checks ran on a fresh clone at `1fc8882`, Python 3.13.12, Node 22.22.2,
dependencies installed from `requirements.txt` and `package-lock.json`.

| Check | Command | Result |
| --- | --- | --- |
| Python suite | `python -m unittest discover` | **782 passed**, 1 expected skip, 84.1 s |
| Browser smoke | `playwright test` | **3 passed**, 9.8 s |
| TypeScript | `npx tsc --noEmit --incremental false` | **clean**, no output |
| Lint | `npx eslint .` (repo ignore set) | **clean**, no output |
| Live server | `uvicorn sbepv.api.main:app --app-dir src` | starts clean, `/healthz` → `{"status":"ok"}` |

Manual verification against the running server at `127.0.0.1:8111`, driven
through Chromium:

- All four workflow tabs rendered and switched without console errors or failed
  requests, other than the favicon described in §5.3.
- Viewports 1440×1000, 820×1180 and 390×844 were checked for horizontal
  overflow. `scrollWidth` equalled `clientWidth` at every width; the layout
  stacks correctly on a phone-width screen.
- Empty and unconfigured states render honestly. With no promoted baseline the
  Annual tab shows "No promoted calibration available — Physics only" and names
  the consequence rather than failing.
- The Solar Agent drawer opens, offers five seeded prompts, and states the
  confirmation boundary ("Agent scenarios cannot replace the active baseline
  without your action").

### 2.1 Environment note, not a repository defect

`@playwright/test` is pinned at 1.63.0, which expects a Chromium revision that
was not present in this container; the pre-installed binary was used via
`launchOptions.executablePath` to run the smoke tests. This is an artifact of
the review container. It is recorded only so the result above is reproducible,
and it needs no change in the repository.

---

## 3. What is already right

These are stated because a remediation list read alone gives a misleading
impression of the codebase.

- **Job failures do not leak internals.** A run submitted with no
  `BAZEFIELD_API_KEY` fails with `The model run failed. Review server logs and
  retry.` The `BazefieldError` and its traceback stay in the server log. That is
  the correct direction for a shared deployment. (The message has a separate
  usability problem — see §5.2.)
- **Source integrity is enforced, and the tests prove it.** The suite exercises
  tamper detection on both sides of the TEA boundary: a sealed payload mutated
  during publication and a frozen snapshot whose SHA-256 no longer matches both
  raise rather than publish. Those tracebacks in the test output are expected
  negative-path coverage.
- **Lease fencing recovers from a dead worker.** Expired leases are swept and
  marked `interrupted` at startup, and a lost lease discards its result rather
  than overwriting a newer attempt.
- **Accessibility has had real attention.** 95 `aria-labelledby`, 60
  `aria-describedby`, 57 `aria-label`, 29 `aria-live` regions, focus styles
  across ten stylesheets, and four `prefers-reduced-motion` blocks. This is
  well beyond what an internal tool usually carries.
- **Source hygiene.** Zero `TODO`, `FIXME`, `XXX` or `HACK` markers and zero
  `console.log` calls in `src/` and `frontend/`.

---

## 4. Blockers

### 4.0 A 12-year annual selection exceeds 2 GB and will OOM-kill the service

**Severity: critical. This is the highest-priority item in this document and it
supersedes §4.1 in ordering.**

Added 2026-09-10 after a targeted capacity test. Unlike the rest of this audit,
this section reports a failure that is reproducible on the current deployment
target (Render, 2 GB / 1 CPU), not a usability gap.

#### What was measured

Peak process RSS of the real annual model path, one clean subprocess per size,
reading `VmHWM` so NumPy buffers are counted (`tracemalloc` undercounts them):

| Years (hourly) | Rows | Peak RSS | % of 2,048 MB |
| --- | --- | --- | --- |
| 1 | 8,760 | 348.7 MB | 17% |
| 2 | 17,520 | 516.4 MB | 25% |
| 4 | 35,040 | 851.0 MB | 42% |
| 8 | 70,080 | 1,518.8 MB | 74% |
| **12** | **105,120** | **2,183.4 MB** | **107% — over the limit** |

Least-squares fit across that 12× range:

```
peak_RSS_MB = 182.9 + 19.50 KB per row
R² = 0.999998        max residual = 1.5 MB
```

The relationship is linear to within 1.5 MB at every measured point, so the
figures below are interpolation, not speculation.

Adding the measured API-process baseline (234 MB resident after serving the
dashboard once, against a ~180 MB import baseline, so ~54 MB of app overhead):

```
service peak ≈ 237 MB + 19.50 KB/row
12 years hourly → 237 + 2,002 = 2,239 MB   vs a 2,048 MB limit
```

Derived ceilings on a 2 GB instance:

| Threshold | Max rows | Max years hourly |
| --- | --- | --- |
| 2,048 MB hard limit | ~95,300 | **10.9** |
| 1,638 MB (80% safety line) | ~73,700 | **8.4** |

This matches the reported experience exactly: 8 years works because it lands at
74–77% of the limit, and 12 years does not.

#### Why the row-count gate does not protect against this

`ANNUAL_RUN_MAX_ROWS = 1_048_575` (`src/sbepv/api/config.py:122`) exists so the
series stays exportable to Excel. It is not a memory budget, and it is roughly
eleven times too permissive to act as one. Crossing the gate against measured
memory, for a 12-year selection:

| 12 years @ interval | Rows | Row gate | Projected peak |
| --- | --- | --- | --- |
| 1 min | 6,311,520 | rejected | — |
| 5 min | 1,262,304 | rejected | — |
| **8 min** | **788,940** | **ACCEPTED** | **~15.3 GB** |
| 10 min | 631,152 | ACCEPTED | ~12.3 GB |
| 15 min | 420,768 | ACCEPTED | ~8.3 GB |
| 30 min | 210,384 | ACCEPTED | ~4.2 GB |
| 60 min | 105,192 | ACCEPTED | ~2.2 GB |

**Every 12-year selection the API currently accepts exceeds 2 GB**, including
the coarsest one. The finest accepted interval (8 minutes, a whole-minute
divisor of 1440) projects to roughly 15 GB.

There is no chunking and no memory guard anywhere on this path — confirmed by
search across `model.py`, `worker/run_annual.py` and `api/validation.py`.

#### Why year count multiplies memory directly

`src/sbepv/worker/run_annual.py:318` concatenates every selected period into a
single frame (`interval_data = pd.concat(interval_frames, ignore_index=True)`),
and line 406 calls `model.run_model` **once** with the combined series. The
per-period loop above it downloads MIDC data; it does not partition the model
run.

The memory itself is in `run_modelchain_for_axis_tilts`
(`src/sbepv/model.py:1426`), which builds a pvlib `PVSystem` holding **73
arrays** — one per unique as-built tilt — and calls `mc.run_model(weather)` on
all of them at once. pvlib then materializes, for all 73 arrays simultaneously,
the POA irradiance components, tracking angles, AOI, cell temperature, and the
full single-diode DC result frame. That is the 19.50 KB/row.

The stage is confirmed to be the pipeline peak: full `predict_ac_power` at
17,520 rows peaked at **517.1 MB**, against **516.4 MB** for the ModelChain
stage alone — a 0.7 MB difference. The Solectria loop, energy integration and
output frame add essentially nothing, so the scaling law above describes the
whole run.

#### Blast radius: this takes down the service, not just the job

The model worker is a **thread inside the API process**, started at
`src/sbepv/api/main.py:229`. The running server was confirmed to be a single
process with 9 threads.

An out-of-memory kill therefore terminates the whole dashboard: every user's
session, not only the run that caused it. Render restarts the service, the
expired lease is swept and the job is marked `interrupted`, so **stored data and
promoted baselines stay intact** — the integrity design holds. Availability does
not. A single analyst ticking twelve year checkboxes takes the dashboard down
for everyone, and nothing in the UI warns them.

#### The fix, verified

Chunking the ModelChain along the time axis is **numerically exact**, not an
approximation. Every stage on this path is memoryless across time: SAPM cell
temperature is steady-state (`TEMPERATURE_MODEL_PARAMETERS = {"a": -3.47,
"b": -0.0594, "deltaT": 0}`, `src/sbepv/model.py:252`), and solar position,
tracking with backtracking, IAM and the single-diode solution are all
per-instant.

This was tested rather than assumed. Running 35,040 rows whole, versus in
8,760-row blocks, and comparing every output array:

```
arrays compared        : 219  (73 tilts × 3 outputs)
NaN patterns identical : True
max abs difference     : 0.000000e+00
BIT-IDENTICAL          : True
```

Measured effect on the 12-year case, in a clean process:

| 12 years hourly (105,120 rows) | Peak RSS |
| --- | --- |
| Current (single ModelChain call) | 2,183.4 MB |
| Chunked into one-year blocks | **728.8 MB** |

A **67% reduction**, comfortably inside 2 GB, and it lifts the ceiling well past
12 years rather than merely clearing it.

#### Recommended remediation

**Immediate, before any rollout — an admission guard.** Reject a selection whose
projected peak exceeds a configured budget, in `_validate_annual_row_count`
(`src/sbepv/api/validation.py:230`), which already computes `expected_rows`. Add
a second check against a `PV_DASHBOARD_MEMORY_BUDGET_MB` setting using the
measured 19.50 KB/row, defaulting to about 70% of instance memory. The 422 it
raises should name the number of years or the interval that would fit, so the
message is actionable. This is a few hours of work and converts a service-wide
outage into a clear rejection at submit time.

**Durable fix — chunk the ModelChain.** Partition inside
`run_modelchain_for_axis_tilts` (or at its call site,
`src/sbepv/model.py:1988`), accumulate per-tilt arrays, and concatenate. The
equivalence proof above means this can be regression-tested against current
output for bit-identity rather than a tolerance. Once it lands, raise the
admission guard's budget rather than removing it.

**Do not simply cap the year selector at 8.** It hides the problem at the
current instance size, silently becomes wrong if the plan changes, and still
leaves the 8-minute-interval path projecting to ~15 GB.

**Note on the estimate's provenance.** 19.50 KB/row was measured on a 4-CPU
container with synthetic clear-sky weather at hourly geometry. Real MIDC data
with missing-value handling may shift it somewhat. Re-measure on the Render
instance before setting the production budget, and set the default
conservatively.

### 4.1 A multi-hour job can be queued with no warning, on one worker thread

**Severity: high. This is the finding most likely to produce a bad first
impression.**

`predict_ac_power` was benchmarked directly on synthetic clear-sky weather at
two problem sizes:

| Rows | Wall time | Per row |
| --- | --- | --- |
| 288 (1 day @ 5 min) | 16.3 s | 56.7 ms |
| 1,440 (1 day @ 1 min) | 37.8 s | 26.3 ms |

Fixed setup cost amortizes with size, so 26 ms/row is the fair figure for a
long run. Extrapolated to the selections the UI actually offers:

| User selection | Rows | Estimated runtime |
| --- | --- | --- |
| Full year, hourly | 8,760 | ~4 min |
| Full year, 5-minute | 105,120 | ~46 min |
| Full year, 1-minute | 525,600 | **~3.8 hours** |
| `ANNUAL_RUN_MAX_ROWS` ceiling | 1,048,575 | **~7.6 hours** |

Three facts compound:

1. `src/sbepv/api/config.py:122` sets `ANNUAL_RUN_MAX_ROWS = 1_048_575`, and the
   README advertises 1-minute intervals and multi-year selection. The row cap
   was chosen so the series stays exportable to Excel, which is a different
   constraint from what the worker can finish in a sitting.
2. `src/sbepv/worker/loop.py:41` starts **one** thread named
   `solar-model-worker` per process. Calibration, annual and TEA jobs all
   serialize through it. A second analyst's job waits behind the first.
3. Nothing in `frontend/` estimates or warns about duration. A search across
   `frontend/js/` and `frontend/html/` for duration language returns no
   user-facing estimate. The queued state renders as the word "Queued" with no
   position and no ETA.

The deployment target sharpens this: `render.yaml` declares `plan: starter`, a
single CPU.

**Consequence.** An analyst selects 1-minute resolution because finer looks
better, waits, sees "Queued" or a slow-moving bar, and concludes the dashboard
is broken. A colleague starting a run at the same time waits behind them with no
indication why.

**Recommended remediation, in order of value:**

- **(a) Estimate before submit.** The row count is already computed for the
  `ANNUAL_RUN_MAX_ROWS` check in `src/sbepv/api/validation.py:241`. Multiply by
  a calibrated per-row constant and show the estimate next to the run button.
  Require an explicit acknowledgement above a threshold — 30 minutes is a
  reasonable first cut.
- **(b) Show queue position.** The durable registry can already count `queued`
  jobs ahead of a given `job_id`. Surfacing "2 runs ahead of yours" in the
  status payload turns an apparently-hung UI into an honest one, and needs no
  scheduler change.
- **(c) Decide the row ceiling on runtime, not just on Excel.** Consider a
  separate, lower cap for interactive runs, keeping the 1,048,575 export ceiling
  for what the system can serialize.
- **(d) Only then consider concurrency.** More workers on a 1-CPU instance will
  not help; this is a plan-sizing decision, and it should follow (a)–(c) rather
  than precede them.

### 4.2 Authentication is fail-open

**Severity: high. Low effort to fix.**

`src/sbepv/api/security.py:31` returns `None` when `DASHBOARD_BASIC_USER` is
empty, and every request then passes unauthenticated. The docstring is explicit
that this is intended local-development behaviour, and the paired-configuration
check (both variables or neither) is well written.

The gap is that nothing distinguishes local development from production. Both
credentials are `sync: false` in `render.yaml`, meaning they live only in the
Render dashboard. If either is cleared, unset during a service migration, or
missed when a second service is created, the deployment serves the full
dashboard — holding a live Bazefield key and a live OpenAI key — to anyone with
the URL, and fails open silently.

**Recommended remediation:** make the absence of credentials fatal in a
production context rather than permissive. A `PV_DASHBOARD_REQUIRE_AUTH`
variable, set in `render.yaml`, that raises at startup when credentials are
missing preserves the local-development path exactly while removing the silent
failure mode. Refusing to boot is the correct behaviour here: a service that
does not start is a visible incident, an open one is not.

### 4.3 Unresolved blueprint drift in `render.yaml`

**Severity: medium. Blocks a clean deploy, not the product.**

`render.yaml:24` declares `plan: starter` while the comment above it records
that the running service reports `1c-2g`. The file also documents that the live
service hardcodes `--port 8000` rather than `$PORT`.

The drift is deliberately recorded rather than silently reconciled, which is the
right call — the comment correctly warns that guessing the plan value could
downgrade and restart a live service. But it remains unresolved, and it sits
directly on the path of any deployment made to support a rollout.

**Recommended remediation:** confirm the correct plan value in the Render
dashboard, set it in the file, and run `render blueprints validate ./render.yaml`
reading the planned service list before the first sync. Do this on a quiet day,
not on launch day.

---

## 5. High-value fixes

### 5.1 No response compression

**Severity: medium. Effort: one line. Best return in the repository.**

The assembled dashboard is served as a single self-contained document:

```
GET /  →  200,  content-length: 1,562,505,  cache-control: no-store
```

There is no compression middleware in `src/sbepv/api/main.py`; only
`CORSMiddleware` is registered, at line 247. Measured against the served bytes:

| Encoding | Size | Reduction |
| --- | --- | --- |
| Identity (current) | 1,562,505 B | — |
| gzip -9 | 240,408 B | **84.6%** |

Every visitor downloads 1.53 MB, and `no-store` means every reload does it
again. Adding `GZipMiddleware` next to the existing CORS registration recovers
almost all of it.

The deeper version of this fix — splitting `frontend/` assets into separately
cacheable files with hashed names — is a larger change and is **not**
recommended as part of a readiness push. The single-document assembly is
deliberate and is covered by `test_dashboard_build.py`. Compression captures
most of the benefit at a fraction of the risk.

### 5.2 Error messages are inconsistent in both directions

**Severity: medium. This is what generates support tickets.**

Two failure surfaces disagree about how much to say, and each is wrong in the
opposite direction.

**Over-sharing.** `src/sbepv/agent/chat.py:576` returns
`OPENAI_API_KEY is not available to the server process.` as a 503 `detail`, and
the chat drawer renders that string verbatim in the message thread. Confirmed in
the browser: an end user typing a question sees an internal environment variable
name and a statement about the server process. It names infrastructure to an
audience that cannot act on it.

**Under-sharing.** `src/sbepv/worker/loop.py:210` and
`src/sbepv/worker/completion.py:192` both return `The model run failed. Review
server logs and retry.`, with the equivalent string at
`src/sbepv/worker/run_technoeconomic.py:1190`. Keeping the traceback server-side
is correct. Directing an analyst to server logs they cannot read is not, and the
same sentence covers a missing credential, a Bazefield outage, an invalid date
range, and an out-of-memory condition. Neither the user nor a support engineer
without shell access can distinguish them.

**Recommended remediation:** classify failures into a small set of user-facing
causes — configuration, upstream data source, invalid request, capacity — and
map each to a sentence that names the next action and who owns it
("The measured-data service could not be reached. This is a configuration issue;
contact the dashboard administrator."). Keep the traceback in the log, and add a
short correlation id to both the log line and the UI message so a support
request can be tied to a specific run. For chat, replace the raw detail with a
configuration-class message from the same set.

### 5.3 Missing favicon

**Severity: low. Effort: minutes. Disproportionately visible.**

`GET /favicon.ico` returns 404 on every page load — the only console error
observed. `frontend/html/document.template.html` declares no `<link rel="icon">`,
and `public/` contains `og.png`, `og-calibration.png` and `annual-warning.png`
but no icon.

`public/` is already served (`GET /annual-warning.png` returns 200), so adding
the file and one `<link>` line to the template head completes it. On a dashboard
this carefully designed, a blank browser tab is a conspicuous omission — and
users keep this page open in a pinned tab all day.

---

## 6. A product decision, not a defect

### 6.1 The workspace is shared, and that is currently implicit

There is one Basic-auth credential pair and therefore one principal;
`request.state.authenticated_principal` (`src/sbepv/api/main.py:276`) resolves to
the single configured username for everyone. `config.SERVER_SESSION_ID` is
process-wide, not per browser.

Saved results follow from that. `AgentStore.list_saved_results`
(`src/sbepv/store.py:2642`) takes no user or session argument and returns rows
for the whole deployment. `SAVED_RESULTS_LIMIT = 10` (`src/sbepv/store.py:24`) is
a deployment-wide ceiling, and the eleventh save is **rejected** with
`at most 10 results can be saved` rather than evicting an older entry.

Rejecting rather than evicting is the safer choice and is clearly deliberate.
The consequence still needs stating: every analyst sees, can rename, and can
delete every other analyst's saved results, and ten saves across the whole team
fills the drawer for everyone.

For a single co-located team sharing one login, this is a defensible design. It
becomes a problem only when it is discovered rather than announced — the first
time someone loses a slot or finds their saved run renamed.

**Recommended action:** decide explicitly. Either (a) document the shared
workspace in the UI, naming the ten-slot team-wide limit where the drawer is
shown, or (b) if per-analyst separation is wanted, that is a real feature — per
user identity, scoped queries, and a per-user limit — and should be scoped as
such rather than patched in. Do not leave it undocumented.

---

## 7. Correction to an earlier statement in this review

An earlier verbal summary given to the requester stated that job cancellation
only checks between stages and would not promptly stop a long model run. **That
was wrong**, and the report supersedes it.

The actual chain: `predict_ac_power` invokes `progress_cb` roughly 100 times
across the Solectria loop (`progress_interval = max(1, (n + 99) // 100)`,
`src/sbepv/model.py:2020`), that callback is wired through `model_progress` to
`set_progress` (`src/sbepv/worker/run_annual.py:402`), and `set_progress` calls
`_check_job_cancelled` on every invocation
(`src/sbepv/worker/run_annual.py:133`).

Cancellation is therefore checked about every 1% of the model loop. On a 3.8-hour
run that is roughly a 2-minute worst-case latency, not a stage-length one. This
needs no code change. It is worth one sentence in the UI near the cancel control
on long runs, and nothing more.

---

## 8. Polish, for later

Recorded for completeness. None of these should compete with §4 or §5.

- **No dark mode.** Zero `prefers-color-scheme` rules across `frontend/css/`.
  For a dashboard kept open all day this is a genuine comfort feature, but it is
  a design project, not a fix.
- **No skip-to-content link.** The page carries a persistent side nav and header
  before main content. Given the ARIA coverage already present, this is a
  conspicuous small gap for keyboard users.
- **`frontend/js/06-technoeconomic.js` is 7,481 lines** — 39% of the 19,156-line
  frontend total, and roughly seven times the next largest file. It is not
  causing a defect today; it is the file most likely to make the next TEA change
  expensive. If it is split, split it along the boundaries the workflow already
  has (source selection, calculation lifecycle, results rendering, exports)
  rather than by size.
- **The draggable agent launcher** overlaps non-interactive text at some scroll
  positions. It was checked programmatically across all four tabs: no
  interactive element is obscured at the default position, and the control is
  user-draggable by design. Cosmetic only; no action recommended.

---

## 9. Suggested sequence

Ordered so that each step is independently shippable and the highest-risk items
land first.

| # | Change | Section | Rough effort |
| --- | --- | --- | --- |
| 0 | **Memory admission guard on annual selections** | §4.0 | **~half day, do first** |
| 1 | Fail-closed auth behind an explicit production flag | §4.2 | ~1 hour |
| 2 | `GZipMiddleware` | §5.1 | minutes |
| 3 | Favicon and `<link rel="icon">` | §5.3 | minutes |
| 4 | Chunk the ModelChain by year (bit-identity regression test) | §4.0 | ~1–2 days |
| 5 | Pre-submit runtime estimate and threshold acknowledgement | §4.1(a) | ~half day |
| 6 | Queue position in the status payload and the UI | §4.1(b) | ~half day |
| 7 | Failure classification and correlation id | §5.2 | ~half day |
| 8 | Resolve `render.yaml` plan drift | §4.3 | ~1 hour, needs dashboard access |
| 9 | Decide and document the shared-workspace model | §6.1 | product decision |

Item 0 gates everything else — until it lands, a single selection can take the
service down, and no other improvement matters at that moment. Items 1–3 are
safe to do together. Item 4 is the durable fix that lets the guard's budget be
raised. Items 5–7 change the end-user experience most and deserve their own
verification.

Items 0 and 4 share one regression test worth writing first: assert that a
chunked run reproduces a whole run bit-for-bit, and that a selection projected
past the budget is rejected at submit rather than at OOM.

---

## 10. Scope and authorization notes for whoever implements this

- This audit changed **no** production code. The working tree was left clean and
  the full suite was green at the time of writing.
- Nothing recommended here touches Autonomy, the Decision Agent, or TEA v6. The
  approval boundary in `AGENTS.md` is unaffected by every item above, and no
  item requires Cliff Ho approval to begin.
- §5.1 deliberately stops short of restructuring the frontend build. The
  single-document assembly is contract-covered by `tests/test_dashboard_build.py`
  and should not be changed as part of a readiness push.
- §4.1(a) needs a calibrated per-row constant. The 26 ms/row figure here was
  measured on a single container under one weather profile and should be
  re-measured on the deployment target before it is shown to a user as an
  estimate. Prefer showing a conservative range over a precise-looking number.
