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

---

# Hybrid Autonomy Workspace Phase 0/1 — design QA

**Evidence**

- Source visual truth: `analysis/autonomy-qa/existing-dashboard-calibration-1440x1000.jpg`, a fresh browser capture of the existing dashboard visual language and shared components.
- Controlling interaction truth: `docs/HYBRID_AUTONOMY_WORKSPACE_PRODUCT_CONTRACT_V1.md`; `docs/UNIFIED_AUTONOMY_TEA_PRODUCT_CONTRACT_V1.md` supplies the end-state boundary and the hybrid contract wins on conflict.
- Implementation, desktop Investigation: `analysis/autonomy-qa/autonomy-desktop-evidence-needed-final-1440x1000.jpg`.
- Implementation, desktop Decision Brief: `analysis/autonomy-qa/autonomy-desktop-signed-recommendation-1440x1000.jpg`.
- Implementation, tablet: `analysis/autonomy-qa/autonomy-tablet-running-1024x900.jpg` and `analysis/autonomy-qa/autonomy-tablet-evidence-drawer-1024x900.jpg`.
- Implementation, mobile: `analysis/autonomy-qa/autonomy-mobile-no-case-390x844.jpg`, `analysis/autonomy-qa/autonomy-mobile-calibration-blocked-390x844.jpg`, `analysis/autonomy-qa/autonomy-mobile-partial-390x844.jpg`, and `analysis/autonomy-qa/autonomy-mobile-signed-recommendation-390x844.jpg`.
- Full visual-language comparison input: `analysis/autonomy-qa/autonomy-style-comparison-1440x1000-pair.jpg`.
- Focused header, navigation, and primary-card comparison input: `analysis/autonomy-qa/autonomy-style-focused-comparison.jpg`.
- Requested CSS viewports: desktop 1440 × 1000, tablet 1024 × 900, and mobile 390 × 844 at DPR 1. The in-app browser captures its page surface at 1425 × 970, 1009 × 887, and 375 × 812 pixels respectively.
- States visually inspected: no case, blocked, evidence needed, ready to confirm, running, partial results, completed results, decision ready, and signed.

No selected Option 2 or Option 3 raster mockup exists in the approved-plan folder. The older Option 1 forecast artifact is a rejected direction and was not treated as a pixel target. Accordingly, this pass compares visual language and component fidelity against the live existing dashboard while checking layout, content, authority, and transitions against the controlling written hybrid contract; it makes no false pixel-equivalence claim to the rejected mockup.

**Findings**

- No actionable P0, P1, or P2 findings remain.
- Fonts and typography: the implementation retains the dashboard's existing Inter/system stack, uppercase teal eyebrows, compact metadata, dense table labels, and heading weights. Long decision text wraps without clipping at all three breakpoints.
- Spacing and layout rhythm: desktop uses the approved 320 px / flexible / 320 px Investigation grid and full analysis grid; tablet uses a two-column workspace plus modal evidence drawer; mobile uses single-column cards, 44 px navigation targets, and a 16 px fixture selector. No page-level horizontal overflow remains.
- Colors and visual tokens: teal remains navigation and primary action, green indicates accepted or complete, amber indicates provisional or partial, red indicates hard blocks or retained conflict, and blue-gray carries informational provenance. Existing borders, radii, surfaces, shadows, and focus rings are reused.
- Image quality and asset fidelity: this workflow requires no photography, illustrations, logos beyond existing product branding, or novel raster assets. No placeholder imagery or invented decorative asset was introduced.
- Copy and content: every quantitative value is labeled as fixture data; the interface explicitly says no jobs, evidence, reports, agent requests, or server changes occur. Partial results withhold completed-only recommendation and reversal content, failed values display as unavailable, and signed copy records disposition, owner, rationale, source lock, and basis lock.
- Responsive behavior: desktop Investigation and Decision Brief, tablet running state and evidence drawer, and mobile empty, blocked, partial, and signed states were inspected at their specified sizes. Tables remain within scroll containers, the mobile reversal panel is 347 px wide inside a 375 px page surface, and persistent controls do not cover content.
- Accessibility and behavior: semantic headings, landmarks, tablists, tabs, tabpanels, tables, column scopes, status messages, labels, and native dialogs are present. Stage tabs support Arrow keys, Home, and End; native dialogs contain focus, close on Escape, and restore the trigger; the tablet drawer moves focus to Close, traps Shift+Tab, closes on Escape, and restores its opener. The existing Solar Agent is explicitly `aria-hidden` and inert only in Autonomy, then returns unchanged in other modes. Reduced-motion and forced-colors rules remain present.
- Browser health: final desktop, tablet, and mobile warning/error console logs were empty.

**Comparison history**

1. Initial functional render — blocked.
   - P1: the Autonomy mode called a nonexistent renderer and the job monitor referenced an undefined fixture variable, preventing reliable state rendering.
   - Fix: connected the mode to `autonomyRenderWorkspace` and used the authoritative local fixture identifier throughout job rendering.
   - Post-fix evidence: desktop Investigation and tablet running captures render the expected shared case and job state.
2. Authority and state audit — blocked.
   - P1: grouped confirmation was not fully gated, sign-off input was discarded, provenance labels conflicted, and no-case/partial states exposed contradictory content.
   - Fix: gated confirmation on the exact ready fixture, operator, acknowledgement, and selected scenarios; retained local disposition/owner/rationale; corrected provenance; hid all case surfaces for no-case; and added an explicit partial-only table with failed values withheld.
   - Post-fix evidence: the mobile empty and partial captures show distinct, non-contradictory states; browser interaction checks preserve ready state on invalid confirmation and transition to queued only after a valid review.
3. Responsive Decision Brief pass — blocked.
   - P2: mobile signed view expanded to 562 px because a reversal-table minimum width dictated a nested grid track; the sign-off and lower-grid content inherited that overflow.
   - Fix: constrained nested grid tracks and panels with `minmax(0, 1fr)`, `min-width: 0`, and a bounded table scroll container.
   - Post-fix evidence: the final mobile signed capture has a 375 px page surface, a 347 px reversal panel, and no horizontal overflow.
4. Partial-results visual pass — blocked.
   - P1: the partial preview still displayed the completed recommendation and reversal sections below its warning.
   - Fix: classified the recommendation and lower Decision Brief grid as complete-results-only content while keeping the human authority bar visibly disabled.
   - Post-fix evidence: `autonomy-mobile-partial-390x844.jpg` shows only completed scenario rows, the failed value as unavailable, no aggregate recommendation, and disabled sign-off.
5. Tablet accessibility pass — blocked.
   - P2: the evidence drawer opened visually but initial focus could remain on its launcher.
   - Fix: focus Close immediately and reinforce it after the opening frame; retain the existing trap and focus restoration.
   - Post-fix evidence: browser checks report entry focus on `autonomyCloseRailBtn`, Shift+Tab contained on the final drawer tab, Escape closure, `aria-hidden=true`, and focus restored to `autonomyOpenRailBtn`.
6. Final comparison — passed.
   - The full and focused comparison inputs show the same brand typography, header composition, navigation treatment, surface hierarchy, card density, teal emphasis, borders, and spacing cadence as the existing dashboard. Final desktop, tablet, and mobile captures show no clipping, unintended overlap, or page-level horizontal overflow.

**Primary interactions tested**

- Switch among Calibration, Annual Simulation, existing TEA, Autonomy, and back; existing titles, panels, Solar Agent availability, and calibration input value remain unchanged.
- Traverse Investigation stages with keyboard controls and hear the live stage announcement.
- Open grouped confirmation, reject an empty scenario selection, then accept a valid selected scenario and reach the queued fixture.
- Open and dismiss confirmation and sign-off dialogs with Escape; verify focus restoration.
- Open the tablet evidence drawer; verify modal semantics, focus entry, Shift+Tab containment, Escape closure, and opener restoration.
- Open partial results explicitly; verify no completed recommendation, no completed analysis panels, failed value withholding, and disabled sign-off.
- Record a local Reject sign-off with a named owner and rationale; verify the signed fixture and disabled mutable fields.
- Verify all required lifecycle fixtures, mobile section synchronization, 44 px targets, 16 px mobile controls, and zero horizontal overflow.

**Implementation Checklist**

- [x] Approved plans preserved as versioned repository contracts.
- [x] Shared case, five-stage Investigation Workspace, and deterministic Decision Brief transition.
- [x] Evidence/readiness rail and all 22 fixture states.
- [x] Empty, blocked, running, partial, completed, and signed acceptance states.
- [x] Desktop, tablet, mobile, keyboard, focus, screen-reader, reduced-motion, and forced-colors behavior.
- [x] Existing dashboard modes and Solar Agent behavior preserved.
- [x] Canonical frontend assembly, classic-script ordering, and newline-equivalent Python/Vite builds verified.

**Follow-up Polish**

- P3: when the product adopts a shared icon library, the text-only `More` disclosure can use its established overflow icon without changing behavior.

final result: passed
