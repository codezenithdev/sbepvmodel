# Design QA — Calibrated Annual Simulation, Option 1

## Evidence

- Source visual truth: `C:\Users\Angushylesh(Shylesh)\.codex\generated_images\019fce3f-52b0-7c23-88e4-737741909225\exec-4958f0b6-9844-4898-b263-125ae4b019c4.png`
- Final implementation capture: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\04\019fce3f-52b0-7c23-88e4-737741909225\annual-option1-final-v6.png`
- Full-view comparison: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\04\019fce3f-52b0-7c23-88e4-737741909225\annual-option1-comparison-final.png`
- Focused confirmation-panel comparison: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\04\019fce3f-52b0-7c23-88e4-737741909225\annual-option1-panel-comparison-final.png`
- Mobile confirmation capture: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\04\019fce3f-52b0-7c23-88e4-737741909225\annual-option1-mobile-dialog-asset.png`
- Local preview: `http://127.0.0.1:8000/`

## Capture normalization

- Browser viewport: 1440 × 1024 CSS pixels at approximately 1× device pixel ratio.
- Source dimensions: 1487 × 1058 pixels.
- Implementation dimensions: 1440 × 1024 pixels.
- The full-view comparison resizes the source once with bicubic sampling to 1440 × 1024, preserves the implementation at its native capture size, and places both views side by side with a 48-pixel evidence label band. The comparison output is 2880 × 1072 pixels.
- The focused comparison uses matching 340-pixel confirmation-panel regions and the same label band. Its output is 720 × 1072 pixels.
- State under review: Annual Simulation selected; current promoted calibration verified; inherited settings unchanged; Fall required but unavailable; server-provided Fall ← Spring confirmation open; no annual job or MIDC download started.

## Findings

No actionable P0, P1, or P2 visual issues remain.

- Typography: title hierarchy, dense operational labels, table text, and confirmation-panel emphasis follow the selected reference.
- Spacing and layout: navigation rail, top bar, inherited-calibration strip, three-step configuration layout, seasonal table, and right-side confirmation panel align with the reference structure. At desktop widths the application reserves panel space instead of hiding the form beneath the drawer.
- Color and surfaces: teal navigation/action treatment, pale-green verified state, amber warning state, neutral card borders, and subdued page background match the target palette.
- Assets: the warning mark is a real image asset extracted from the supplied source and served from `public/annual-warning.png`; no text symbol, emoji, CSS drawing, inline SVG, or placeholder is used.
- Copy and content: visible values are live baseline/factor data. The panel shows the exact Spring factors and server-computed setting differences instead of hardcoded mock values.
- Responsive behavior: at 390 × 844 the confirmation becomes a full-height panel, factor values stack, and the panel has no horizontal overflow.
- Accessibility: the confirmation uses dialog and warning semantics, keyboard focus enters the panel, Escape and Cancel close it, and focus returns to the annual-run trigger. Controls retain visible focus states and accessible labels.
- Runtime: primary interactions were exercised in the in-app browser. Console warning and error logs were empty.

## Intentional, requirement-driven differences

- The reference's explanatory bullet list is replaced by exact Spring factors and a modified-settings audit because explicit informed consent is part of the approved plan.
- Annual dates remain the existing independent MIDC controls; the reference's illustrative weather-source/location fields were not introduced.
- The nine inherited settings use the dashboard's existing accessible setting cards instead of a compact mock table so unrelated product patterns and the user's Technoeconomic work remain intact.

These are accepted product-contract differences, not fidelity defects.

## Iteration history

1. Initial browser pass found full-precision factor overflow on mobile and an unreliable dialog-focus return path. Factor rows were stacked at narrow widths and focus return was anchored to the annual-run trigger.
2. Full-view comparison found excess panel width, overlay obstruction, title wrapping, table overflow, and a text-based warning mark. The app now reflows around a 340-pixel panel, shows compact table factors with exact-value tooltips, keeps the title on one line, and uses the source warning asset.
3. Final full-view and focused-region comparisons found no remaining actionable P0, P1, or P2 issues.

## Functional verification

- Current promoted calibration loads and prefills all nine transferable settings.
- Editing an inherited value shows the amber changed state, calibrated value, change count, and restore action.
- A Fall-missing submission opens the server-driven confirmation with exact factors and creates no job before consent.
- Cancel and Escape clear the pending confirmation and restore keyboard focus.
- Full automated suite: 207 tests passed, 1 skipped.
- Production frontend build: passed.
- Python compile check: passed.
- Static diff whitespace check: passed.
- Warning asset route: HTTP 200, `image/png`, 8111 bytes.

The live confirmed MIDC annual run was intentionally not accepted during browser QA, avoiding an external download; the confirmed worker path and output provenance are covered by automated API and model tests.

## Implementation checklist

- [x] Source and implementation compared at normalized dimensions.
- [x] Desktop full view reviewed.
- [x] Confirmation panel reviewed as a focused region.
- [x] Mobile layout and overflow reviewed.
- [x] Primary inherited/modified/restore/confirm/cancel states exercised.
- [x] Keyboard focus and warning semantics reviewed.
- [x] Console checked for warnings and errors.
- [x] Automated regression suite and production build passed.
- [x] No P0/P1/P2 issue remains.

final result: passed
