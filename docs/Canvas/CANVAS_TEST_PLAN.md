# Canvas Component — Manual Test Plan

**Scope:** All features introduced/modified in the canvas split panel, fullscreen mode, inline card, and panel toggle sessions.

**Prerequisites:**
- Server running (`python -m trusted_data_agent.main`)
- At least one LLM profile configured
- Canvas split mode toggle available in capabilities header

---

## Part 1: Inline Card Rendering

### T1.1 — Card appears when split mode is ON
1. Enable split mode via the canvas toggle in the capabilities header
2. Submit: "Write a Python function to calculate fibonacci numbers. Use the canvas to show the code."
3. **Expected:** An inline card appears in chat with:
   - Title ("Fibonacci Function" or similar) + code icon
   - Language badge ("PYTHON · 15 LINES")
   - Scrollable code preview (~10 visible rows)
   - Action text: **"View in Canvas →"**

### T1.2 — Preview is scrollable without opening panel
1. From T1.1, scroll inside the code preview area
2. **Expected:** Preview scrolls vertically. Clicking inside the preview does NOT open the split panel.

### T1.3 — Click card header opens split panel
1. Click anywhere on the card (outside the preview area)
2. **Expected:** Split panel slides open on the right (50% width). Full canvas renders with tabs and toolbar. Card badge changes to **"Expanded in side panel →"**

### T1.4 — Click card header again closes split panel
1. Click the same card again
2. **Expected:** Split panel closes. Card badge reverts to **"View in Canvas →"**

### T1.5 — Multiple cards track badges correctly
1. Generate 3 canvas responses in sequence
2. Click card #2 to open panel
3. **Expected:** Only card #2 shows "Expanded in side panel →", others show "View in Canvas →"
4. Close the panel
5. **Expected:** All cards show "View in Canvas →"

---

## Part 2: Merged Header (No Duplicate Headers)

### T2.1 — Single header in split panel
1. Open canvas in split panel (click an inline card)
2. **Expected:** Only ONE header visible at the top of the canvas, containing:
   - Title + tab bar (left side)
   - Toolbar buttons: Templates, Copy, Download, Expand, line count, language badge
   - Separator line (thin vertical divider)
   - Fullscreen button (expand arrows icon)
   - Close button (X icon)
3. **No duplicate "Fibonacci Function" header** — the old split panel header is hidden

### T2.2 — Toolbar button hover states
1. Hover over fullscreen and close buttons in the toolbar
2. **Expected:** Background highlights on hover, consistent with other toolbar buttons (Templates, Copy, etc.)

---

## Part 3: Fullscreen Mode

### T3.1 — Enter fullscreen
1. Open canvas in split panel
2. Click the fullscreen button (expand arrows) in the toolbar
3. **Expected:**
   - Canvas fills the entire viewport below the top app header (UDERIA logo bar)
   - **No gap on the left side**
   - **No clipping on the right side** — all toolbar buttons fully visible
   - Fullscreen button icon changes to **shrink arrows** (exit fullscreen)
   - Button tooltip changes to "Exit fullscreen"

### T3.2 — Exit fullscreen returns to split mode
1. In fullscreen mode, click the fullscreen button (shrink arrows)
2. **Expected:** Canvas returns to **split mode** (side-by-side with chat). Panel stays open at 50% width. Does NOT close the panel entirely.

### T3.3 — Close button exits fullscreen AND closes panel
1. Enter fullscreen mode again
2. Click the **close button (X)** instead
3. **Expected:** Exits fullscreen AND closes the panel completely. All UI panels restored.

### T3.4 — Fullscreen fills edge-to-edge
1. Enter fullscreen mode
2. Resize browser window
3. **Expected:** Canvas stays edge-to-edge. No gaps on any side. Content adjusts to viewport.

### T3.5 — Top app header remains visible
1. Enter fullscreen mode
2. **Expected:** The UDERIA logo bar with status indicators (MCP, LLM, CTX, KNW, CCR, SSE) remains visible at the top. Canvas sits directly below it.

### T3.6 — Multiple fullscreen toggle cycles
1. Enter fullscreen → exit (returns to split) → enter fullscreen → exit → enter → close (X)
2. **Expected:** Each transition is smooth. Icon always matches state. No visual glitches or stale state.

---

## Part 4: Panel Toggle Buttons

### T4.1 — History toggle (left) is vertically centered
1. With canvas panel closed, observe the history panel toggle (>> arrows on the left)
2. **Expected:** Button is vertically centered in the main content area

### T4.2 — Status toggle (right) is vertically centered
1. Observe the status panel toggle (<< arrows on the right)
2. **Expected:** Button is vertically centered, same as history toggle

### T4.3 — Resource/capabilities toggle (center) stays at top
1. Observe the capabilities panel toggle (down chevron at top center)
2. **Expected:** Button is at the top of the content area (not centered), close to the top edge

### T4.4 — All toggles are transparent
1. Observe all three toggle buttons at rest (not hovered)
2. **Expected:** Buttons are barely visible (20% opacity). Orange circle + icon both faded equally.

### T4.5 — Toggles become visible on hover
1. Hover over each toggle button
2. **Expected:** Button smoothly transitions to 100% opacity. Orange background and white icon fully visible.

### T4.6 — Toggles are close to borders
1. Check the position of history toggle relative to the left edge
2. Check the position of status toggle relative to the right edge
3. **Expected:** Minimal gap between buttons and panel edges (0px container padding)

### T4.7 — Toggles hidden in fullscreen mode
1. Enter canvas fullscreen mode
2. **Expected:** All three toggle buttons are not visible (covered by the fixed-position canvas panel)

---

## Part 5: Dynamic Badge Text

### T5.1 — Default state shows "View in Canvas"
1. Generate a canvas response with split mode ON
2. **Expected:** Card action text shows **"View in Canvas →"**

### T5.2 — Opening panel changes to "Expanded in side panel"
1. Click the card to open the split panel
2. **Expected:** Card action text changes to **"Expanded in side panel →"**

### T5.3 — Closing panel reverts to "View in Canvas"
1. Close the panel (click card again, or click X)
2. **Expected:** Card action text reverts to **"View in Canvas →"**

### T5.4 — All cards reset on panel close
1. Generate 3 cards, open panel from card #2
2. Close the panel
3. **Expected:** ALL cards show "View in Canvas →" — no card left in "Expanded" state

---

## Part 6: Inline Compact Mode (Split Mode OFF)

### T6.1 — Compact view renders when split mode is OFF
1. Toggle split mode OFF
2. Generate a canvas response
3. **Expected:** Read-only code viewer renders inline (not a card). Has copy button and "Open in Canvas" expand button.

### T6.2 — "Open in Canvas" activates split mode
1. Click the "Open in Canvas" button on the compact viewer
2. **Expected:** Split mode activates globally. Canvas opens in split panel. Toggle button shows active state.

---

## Part 7: Cross-Cutting Concerns

### T7.1 — Session switching closes fullscreen
1. Enter fullscreen mode
2. Switch to a different session in the history panel (if accessible)
3. **Expected:** Fullscreen exits cleanly. Panel closes. No stale CSS classes.

### T7.2 — Multiple languages
1. Generate canvases in SQL, Python, and JavaScript
2. Open each in split panel
3. **Expected:** Each renders correctly with proper syntax highlighting, language badge, and line count.

### T7.3 — Light theme compatibility
1. Switch to light theme
2. Repeat T1.1, T2.1, T3.1
3. **Expected:** Cards, toolbar, and fullscreen mode all render correctly in light theme.

### T7.4 — Long code content
1. Generate a canvas with 100+ lines
2. Check inline card preview
3. Open in split panel
4. Enter fullscreen
5. **Expected:** Preview truncated at ~10 rows (scrollable). Full content in split panel. Fullscreen shows all content.

---

## Test Summary

| Section | Tests | Focus |
|---------|-------|-------|
| Part 1: Inline Card | 5 | Card rendering, click toggle, badges |
| Part 2: Merged Header | 2 | Single header, toolbar integration |
| Part 3: Fullscreen | 6 | Enter/exit, edge-to-edge, split mode return |
| Part 4: Toggle Buttons | 7 | Positioning, transparency, hover |
| Part 5: Dynamic Badge | 4 | State-driven text changes |
| Part 6: Compact Mode | 2 | Split mode OFF behavior |
| Part 7: Cross-Cutting | 4 | Sessions, languages, themes, long content |
| **Total** | **30** | |
