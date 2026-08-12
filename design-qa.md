# Saved Results drawer — design QA

**Evidence**

- Source visual truth: `C:\Users\Angushylesh(Shylesh)\.codex\generated_images\019ff2e0-42b3-7ea1-b91d-d756575c3049\exec-0efb85a8-e20a-4d7c-acdd-3418fa5b6649.png`
- Browser-rendered implementation: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\11\019ff2e0-42b3-7ea1-b91d-d756575c3049\saved-results-desktop.png`
- Full comparison: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\11\019ff2e0-42b3-7ea1-b91d-d756575c3049\saved-results-full-comparison-final.png`
- Focused drawer comparison: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\11\019ff2e0-42b3-7ea1-b91d-d756575c3049\saved-results-drawer-comparison-final.png`
- Responsive capture: `C:\Users\Angushylesh(Shylesh)\.codex\visualizations\2026\08\11\019ff2e0-42b3-7ea1-b91d-d756575c3049\saved-results-mobile.png`
- Desktop viewport and density: 1720 × 914 CSS px at DPR 1; implementation image 1720 × 914 px.
- Source normalization: original 1721 × 914 px; the 1 px right-edge excess and 18 px top presentation bar were removed, then the source was normalized to 1720 × 914 for comparison.
- Mobile viewport and density: 390 × 844 CSS px; full-width drawer, no horizontal overflow, minimum interactive target 44 px.
- State: drawer open, All filter selected, three realistic persisted results, annual item selected, page backdrop visible.

**Findings**

- No actionable P0, P1, or P2 findings remain.
- Fonts and typography: the implementation uses the dashboard's existing Inter/system stack and matches the source hierarchy, weight, compact metadata, and prominent kWh values. No clipping or truncation was observed.
- Spacing and layout rhythm: drawer width, header, count, compact segmented filter, grouped result rows, selected tint, list inset, and pinned footer align with the source. The implementation deliberately preserves the existing dashboard behind the modal instead of recreating the source's underlying calibration state.
- Colors and visual tokens: existing teal, muted gray, border, surface, selected-row, and focus tokens map cleanly to the source. The final backdrop opacity preserves context without competing with the drawer.
- Image and asset fidelity: this workflow contains no product photography or illustrative assets. The close mark reuses the dashboard's established control treatment; there are no placeholder images, CSS drawings, or invented decorative assets.
- Copy and content: title, limit explanation, saved count, workflow labels, saved time, run window, energy, local-storage note, and actions are coherent in the standalone dashboard. MIDC year selections are labeled as years rather than misrepresented as one continuous date range.
- Accessibility and behavior: semantic dialog/tab/card structure, Escape close with focus restoration, keyboard tab behavior, visible focus, `inert` background handling, reduced-motion rules, accessible energy labels, and 44 px mobile targets are present. The drawer is full-screen at 390 px with no horizontal overflow.

**Comparison history**

1. Initial comparison — blocked.
   - P2: the drawer was wider and the segmented filter stretched across the full width, changing the source's compact hierarchy.
   - P2: row density and kWh emphasis were lighter than the source, while the footer occupied less visual weight.
   - P2: the backdrop obscured more page context than the visual target.
   - Fixes: reduced the drawer to 464 px, constrained the desktop filter to 256 px, increased row rhythm and energy hierarchy, restored the source-like footer treatment, and softened the backdrop.
2. Revised comparison — blocked.
   - P2: the result group was slightly too narrow and over-inset relative to the source.
   - Fix: aligned the list to a 26 px leading inset and expanded it to roughly 423 px, matching the focused source region while keeping mobile padding independent.
3. Final comparison — passed.
   - Post-fix evidence shows matching major-region proportions, information hierarchy, selected treatment, row cadence, footer placement, and control density. Remaining differences are dynamic content and the intentionally real underlying annual dashboard state, not drawer fidelity issues.

**Primary interactions tested**

- Open from the persistent Saved Results launcher; close with Escape and return focus to the launcher.
- All, Calibration, and Annual filters; Annual produces one visible saved result.
- View a saved result via GET-only restore without starting a new model run.
- Rename entry, cancel rename, and restore focus to the card's More control.
- Complete rename and confirm the card is re-enabled afterward.
- Preserve selected-card identity after view/reopen.
- Verify mobile full-screen layout, 44 px controls, vertical scrolling, and no horizontal overflow.
- Verify browser console warning/error log is empty in the final desktop and mobile states.

**Implementation Checklist**

- [x] Durable maximum-10 persistence and REST contract.
- [x] Persistent launcher and workflow save actions.
- [x] View, filter, rename, remove, and export controls.
- [x] Loading, empty, error, busy, selected, and responsive states.
- [x] Keyboard, focus, reduced-motion, and mobile accessibility.
- [x] Browser and visual comparison evidence.

**Follow-up Polish**

- P3: replace the textual More label with the product's icon-library vertical-ellipsis icon if that icon becomes part of the shared dashboard asset set.

final result: passed
