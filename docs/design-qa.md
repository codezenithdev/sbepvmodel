# Design QA: option 3 horizontal results redesign

## Evidence

- Source visual truth: `C:\Users\Angushylesh(Shylesh)\.codex\generated_images\019fc06c-ecd0-7052-b899-6e625241c668\exec-21fddb1f-093c-4f7c-b242-ecadf84550d5.png` (1823 x 863 px). This is the selected third concept revised to place the measured-system comparison below both system rows.
- Browser-rendered implementation: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\02\019fc06c-ecd0-7052-b899-6e625241c668\option-3-results-desktop-final.png` (1557 x 891 px).
- Combined comparison input: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\02\019fc06c-ecd0-7052-b899-6e625241c668\option-3-design-comparison-final.png`.
- Responsive evidence: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\02\019fc06c-ecd0-7052-b899-6e625241c668\option-3-results-laptop.png`.
- Browser viewport: 1572 x 900 CSS px at device pixel ratio 1.0. The in-app browser capture surface returned 1557 x 891 px after excluding browser chrome.
- State: desktop calibration results populated with the selected design's exact SolarEdge, Solectria, pre-calibration, and measured-comparison values. A temporary local-only data fixture was used for capture and removed before final verification.
- Density normalization: the implementation results region was cropped to `(272, 47)-(1538, 601)` and both source and implementation were scaled proportionally to 1400 px wide in the combined comparison. No finding is based on browser chrome, sidebar width, or the dynamic results header.
- Primary behavior checked: calibrated baseline visible, ordinary physics-model baseline hidden, prediction-stage label switches by state, SolarEdge precedes Solectria, measured-system comparison follows both rows, no horizontal overflow, and no console errors.

## Full-view comparison

The implementation matches the revised target's left-to-right journey: system identity, original physics-model result, calibrated prediction and model delta, then measured energy. SolarEdge and Solectria remain vertically stacked, with the measured-system comparison as the final section. The grid tracks, colored left rails, neutral dividers, value hierarchy, border radii, and restrained elevation closely match the target while using the dashboard's existing spacing and typography tokens.

The implementation intentionally retains the product's dynamic `Calibration results` heading, explanatory sentence, and `Seasonally calibrated` status badge instead of replacing them with the mock's generic `Model results` heading. This preserves existing run-state behavior without changing the selected results layout.

The 1400 px-wide combined comparison keeps every label, value, unit, separator, and semantic delta/flow mark readable, so a separate focused crop was not required.

## Fidelity surfaces

- Fonts and typography: the existing Inter/system sans stack matches the target's product typography. System names, uppercase stage labels, tabular metric values, units, weights, and line heights preserve the selected hierarchy with no clipping or unintended wrapping at the wide target state.
- Spacing and layout rhythm: both system rows are 157 px high in the final wide capture, separated by 18 px. The comparison strip is 133 px high. Padding, dividers, and radii closely follow the normalized target proportions.
- Colors and visual tokens: SolarEdge uses the existing teal tokens, Solectria uses `--info` blue, and the neutral surface/border/text palette maps directly to the reference. No extra gradient or decorative color was introduced in this results surface.
- Image quality and asset fidelity: the results surface contains no photographic or illustrative assets. The delta and flow marks are semantic result notation rather than substituted decorative imagery.
- Copy and content: every system label, stage label, value, unit, delta, and comparison explanation is preserved. The calibrated and physics-only labels change with the actual result state.
- Responsiveness and accessibility: at the laptop breakpoint the identity spans the first row and the three result stages use `1fr / 1.3fr / 0.9fr` tracks, eliminating metric collisions. At 760 px and below the stages stack with separators and the horizontal flow marker is hidden. Source order stays SolarEdge, Solectria, comparison at every breakpoint. The result shell has equal `clientWidth` and `scrollWidth` (1257 px) in the wide capture.
- States and interactions: the existing result renderer continues to populate the same stable element IDs. Calibrated baselines toggle both `hidden` and the layout class; ordinary physics-model results show `Physics-model prediction` with no empty baseline column. Existing navigation, forms, chart areas, and Solar Agent controls remain unchanged.

## Comparison history

1. Initial wide pass: the selected hierarchy, colors, values, and bottom comparison placement matched, but the rows and comparison were denser than the target. Vertical padding and section gaps were increased to align the normalized proportions.
2. Laptop pass: the four-stage row was too tight when the persistent sidebar reduced available content width; model-delta labels and values crowded adjacent metrics. The responsive transition was moved to 1450 px, the intermediate grid was rebalanced to `1fr / 1.3fr / 0.9fr`, and internal gaps were reduced.
3. Post-fix pass: wide rows measured 1257 px with no horizontal overflow, the laptop layout showed no metric collisions, the comparison remained below both systems, and the browser console reported no errors or warnings.

## Findings

No actionable P0, P1, or P2 findings remain. The dynamic calibration heading is an intentional product-state difference from the visual mock, not design drift.

## Implementation checklist

- Preserve all result element IDs and `applyResult` behavior.
- Keep the comparison strip after `.validation-system-summaries` in DOM order.
- Keep `.has-calibration-baseline` synchronized with the baseline `hidden` state.
- Retain the 1450 px intermediate and 760 px stacked breakpoints.

final result: passed

---

# Historical QA: calibrated and uncalibrated result values

## Evidence

- Source visual truth: `C:\Users\ANGUSH~1\AppData\Local\Temp\codex-clipboard-280590b1-5f43-48fd-a105-b9dcfae4af12.png` (1577 x 698 px).
- Browser-rendered implementation: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\02\019fbffc-c10d-7ce2-be6c-2e5474125222\uncalibrated-values-results.jpg` (1265 x 712 px).
- Browser viewport: 1280 x 720 CSS px; device pixel ratio 1.5. The in-app browser capture surface returned a 1265 x 712 px image.
- State: desktop validation view with a completed seasonal calibration. SolarEdge and Solectria both show the final calibrated result plus the original physics-model energy and delta.
- Density normalization: the user reference is a differently cropped desktop capture at 1577 px wide. Both images were opened together at native resolution and compared by shared card anchors rather than with a whole-page pixel overlay. No finding is based on the differing browser crop or density.

## Full-view comparison

The implementation preserves the two-column SolarEdge/Solectria composition, system-colored top borders and values, measured/predicted tile grid, model-delta band, measured-system comparison, typography hierarchy, card radii, and neutral surfaces visible in the source. Each model card intentionally grows by one compact row to add the requested baseline values without changing the primary result hierarchy.

The new row is visually subordinate: a dashed neutral border, smaller muted values, and the heading `Before calibration` distinguish it from the final calibrated prediction above. `Predicted` and `Delta` labels keep the two values unambiguous. Both cards remain equal height and the result grid has no horizontal overflow (`clientWidth` and `scrollWidth` both 965 px).

## Focused result-card comparison

- SolarEdge: calibrated prediction 511.9 kWh / +0.03%; before calibration 486.4 kWh / -4.94%.
- Solectria: calibrated prediction 441.5 kWh / -0.90%; before calibration 420.1 kWh / -5.70%.
- The original measured, predicted, and delta blocks retain the source layout and emphasis; the added strip uses the same spacing, radius, border, and type tokens.
- Physics-only and legacy-result states are covered by regression tests: the strip is hidden unless the run is calibrated and an object-valued `stats.uncalibrated` payload is available.
- Browser diagnostics: no page error or console message was emitted during reload and fixture rendering.

## Fidelity surfaces

- Fonts and typography: the existing dashboard font stack, uppercase metric labels, weights, line heights, and system-value hierarchy are unchanged. The new 10 px labels and 17 px values remain readable and subordinate.
- Spacing and layout rhythm: the original 18 px card padding, 10 px tile gap, 8 px radii, and delta spacing are preserved. The new row adds an 8 px vertical gap and 10 x 14 px padding without crowding either card.
- Colors and visual tokens: all additions reuse `--surface`, `--border`, `--muted`, and `--muted-strong`; no new palette or decoration was introduced.
- Image quality and asset fidelity: this result surface contains no image asset requiring generation or substitution. Existing system dots and the measured-comparison mark are unchanged.
- Copy and content: `Before calibration`, `Original physics-model result`, `Predicted`, and `Delta` clearly explain the baseline without implying that an uncalibrated direct run was calibrated.
- Responsiveness and accessibility: the comparison containers are hidden semantically by default, use explicit labels, and stack their copy/value groups below 560 px. Missing nullable values render as `n/a` rather than borrowing calibrated totals.

## Comparison history

1. Initial implementation review: no P0/P1/P2 issue was found. The requested values fit as a secondary strip while the source card structure remained intact.
2. Verification: the browser rendered both comparison rows with the expected API values, equal card heights, no horizontal overflow, and no runtime or console error. No visual fix iteration was required.

## Findings

No actionable P0, P1, or P2 findings remain. No P3 follow-up is required for this scoped addition.

final result: passed
