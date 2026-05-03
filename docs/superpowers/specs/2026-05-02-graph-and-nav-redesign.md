# Graph Panel + Nav Bar Redesign

## Overview

Two UI improvements to the NeuroNote workspace:

1. **Graph panel simplification** — remove per-panel filter controls; apply a single global confidence threshold from user preferences. Remove the concept node list so the graph canvas fills the panel.
2. **User avatar dropdown** — make the avatar in the top nav clickable, revealing a settings panel with: user identity, AI mode toggle, cloud API config (when Cloud selected), global confidence threshold slider, and sign out.

---

## Feature 1: Graph Panel Simplification

### What changes

**`web/src/components/graph/LocalGraphPanel.tsx`**

- Remove the `filters` prop and `onFiltersChange` prop entirely.
- Remove all filter UI: depth `<select>`, confidence `<input type="range">`, type `<fieldset>` checkboxes.
- Remove the `handleIncludeTypeToggle` helper.
- Remove the `<ul className="local-graph-node-list">` and all its children.
- Read `confidenceThreshold` from `usePreferences()`. Pass it as the `min_confidence` parameter to the graph API call. Since the panel does not make its own API call (graph data is fetched by `NoteEditor` and passed in as `graph` prop), this value needs to flow from `NoteEditor` into `LocalGraphPanel` — see NoteEditor changes below.
- Hardcode `max_hops=1` and `include_types=["note","entity"]` for all graph fetches.
- D3 canvas height: change from `height={300}` to `height={400}`.
- Keep the stats footer: `"{nodeCount} nodes · {edgeCount} edges"`.

**`web/src/components/editor/NoteEditor.tsx`**

- Add `confidenceThreshold?: number` prop (default `0.9`). `NotesWorkspace` passes `prefs?.confidence_threshold ?? 0.9` — same pattern as `llmMode`.
- Remove `localGraphFilters` state, `setLocalGraphFilters`, and the `DEFAULT_LOCAL_GRAPH_FILTERS` constant.
- Hardcode the graph fetch params: `{ max_hops: 1, limit_nodes: 80, min_confidence: confidenceThreshold ?? 0.9, include_types: ["note", "entity"] }`.
- Remove the `onFiltersChange` prop passed to `<LocalGraphPanel>`.

**`web/src/components/workspace/NotesWorkspace.tsx`**

- Pass `confidenceThreshold={prefs?.confidence_threshold ?? 0.9}` to `<NoteEditor>`. (`prefs` is already loaded via `usePreferences()` in `NotesWorkspace`.)

**`web/src/components/graph/GlobalGraphPanel.tsx`**

- Remove the confidence `<input type="range">` and its label from the filters section.
- Replace `filters.min_confidence` usage with `prefs?.confidence_threshold ?? 0.9` read via `usePreferences()` internally.
- The `min_confidence` field in the local `filters` state can be removed; the global preference drives it.

### Confidence threshold preference

New preference key: `confidence_threshold` (float, 0.5–1.0, default `0.9`).

**`shared/contracts/python/v1/preferences.py`**
```python
confidence_threshold: float = Field(default=0.9, ge=0.5, le=1.0)
```
Add to both `UserPreferences` and `UpdatePreferencesRequest` (optional field with `None` default in update).

**`shared/contracts/ts/v1/preferences.ts`**
```typescript
confidence_threshold: number;  // in UserPreferences
confidence_threshold?: number; // in UpdatePreferencesRequest
```

**`api/src/app/routes/preferences.py`**

The existing PUT handler iterates over the request fields and writes each non-null value to `user_preferences`. Adding `confidence_threshold` to the contract models is sufficient — no route logic changes needed. Verify the handler is generic enough; if it's field-specific, add the new key.

---

## Feature 2: User Avatar Dropdown

### What changes

**`web/src/components/auth/UserMenu.tsx`** — full rewrite.

New behaviour:
- Renders an avatar button (image or initials badge). `aria-label="Open settings"`, `aria-expanded={isOpen}`.
- Clicking the avatar toggles a dropdown panel.
- Clicking outside or pressing Escape closes the dropdown.
- Dropdown is positioned `position: absolute; right: 0; top: calc(100% + 8px)` relative to a `position: relative` wrapper.

Dropdown sections (top to bottom):

1. **User identity** — avatar (32px) + display name (bold, 12px) + email (muted, 11px). Read-only.
2. **AI Mode** — two-pill toggle: `Edge AI` / `Cloud AI`. Calls `updatePreferences({ llm_mode })` + `reloadPrefs()` on change.
   - When `Cloud AI` is selected, show cloud config fields below the toggle:
     - API Key (password input, masked display)
     - Base URL (text input)
     - Model (text input)
     - Save button: calls `updatePreferences({ llm_api_key, llm_base_url, llm_model })` + `reloadPrefs()`. Disables while saving.
   - When `Edge AI` is selected, cloud config fields are hidden.
3. **Confidence Threshold** — label + percentage display + range input (50%–100%, step 5%). On change (debounced 500ms): calls `updatePreferences({ confidence_threshold })` + `reloadPrefs()`.
4. **Sign out** — calls `logoutUser()` then `window.location.href = "/login"`. Styled in danger color.

**Props**: `UserMenu` receives `user: UserProfile | null` (unchanged). Preferences are fetched internally via `usePreferences()`. This keeps the component self-contained and avoids threading preferences through `NotesWorkspace`.

**`web/src/components/workspace/NotesWorkspace.tsx`**

- Remove the existing `<LLMSettings>` modal and its open/close state (`llmSettingsOpen`, `setLlmSettingsOpen`).
- Remove the "Settings" button that opened `LLMSettings` (if any).
- The `<UserMenu>` import/usage signature is unchanged — it already receives `user` prop.
- `WebGPUCheck`, `EdgeConsentDialog`, `EdgeCrashBanner` are unaffected.

**`web/src/components/settings/LLMSettings.tsx`** — delete this file. All its functionality moves into the `UserMenu` dropdown. Update any import that references it.

### Dropdown close behaviour

Use a `useEffect` that adds a `mousedown` event listener to `document` when the dropdown is open, closing it when the click target is outside the dropdown wrapper ref. Clean up on unmount.

### State in UserMenu

```typescript
const [isOpen, setIsOpen] = useState(false);
const [cloudDraft, setCloudDraft] = useState({ llm_api_key: "", llm_base_url: "", llm_model: "" });
const [saving, setSaving] = useState(false);
```

`cloudDraft` is seeded from `prefs` when the dropdown opens (or when `prefs` loads), so the user sees their current values.

---

## CSS

All new styles go in `globals.css` using the existing token system. New classes needed:

- `.user-menu-wrapper` — `position: relative; display: inline-flex`
- `.user-menu-avatar-btn` — resets button styles, cursor pointer, border-radius 50%
- `.user-menu-dropdown` — `position: absolute; right: 0; top: calc(100% + 8px); background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 10px; box-shadow: var(--shadow-panel); min-width: 240px; z-index: var(--z-dropdown); overflow: hidden`
- `.user-menu-section` — `padding: 12px 14px; border-bottom: 1px solid var(--panel-border)`
- `.user-menu-label` — `font-size: var(--text-xs); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px`
- `.user-menu-mode-toggle` — `display: flex; border: 1px solid var(--panel-border); border-radius: 6px; overflow: hidden`
- `.user-menu-mode-btn` — pill button within mode toggle; active state uses `background: var(--accent); color: #fff`
- `.user-menu-signout` — `padding: 8px 14px; font-size: var(--text-sm); color: var(--danger); cursor: pointer`

---

## Testing

**`web/src/components/auth/__tests__/UserMenu.test.tsx`** (new file)

- Renders avatar button (image when `avatar_url` set; initials otherwise).
- Clicking avatar opens dropdown; pressing Escape closes it; clicking outside closes it.
- AI mode toggle calls `updatePreferences` with correct `llm_mode`.
- Cloud config fields appear when Cloud mode is active; hidden when Edge mode is active.
- Save button calls `updatePreferences` with cloud config values.
- Confidence slider calls `updatePreferences` with `confidence_threshold` (debounced — use fake timers).
- Sign out button calls `logoutUser` and redirects.

**`web/src/components/graph/LocalGraphPanel.test.tsx`** (update existing)

- Remove tests that reference `onFiltersChange` or filter UI elements.
- Add: renders graph canvas with correct height (400).
- Add: no filter controls rendered.
- Add: stats footer shows "N nodes · M edges".

---

## Files Modified / Created

| File | Action |
|------|--------|
| `shared/contracts/python/v1/preferences.py` | Add `confidence_threshold` field |
| `shared/contracts/ts/v1/preferences.ts` | Add `confidence_threshold` field |
| `web/src/components/auth/UserMenu.tsx` | Rewrite |
| `web/src/components/auth/__tests__/UserMenu.test.tsx` | Create |
| `web/src/components/graph/LocalGraphPanel.tsx` | Remove filters + node list, bigger canvas |
| `web/src/components/graph/LocalGraphPanel.test.tsx` | Update |
| `web/src/components/graph/GlobalGraphPanel.tsx` | Remove confidence slider, read from prefs |
| `web/src/components/editor/NoteEditor.tsx` | Remove filter state, use prefs threshold |
| `web/src/components/workspace/NotesWorkspace.tsx` | Pass `confidenceThreshold` prop to NoteEditor; remove LLMSettings modal |
| `web/src/components/settings/LLMSettings.tsx` | Delete |
| `web/src/app/globals.css` | Add user-menu CSS classes |

---

## What is NOT in scope

- Landing page and onboarding tutorial — separate spec.
- Changing the graph layout algorithm or node colors.
- Adding more preference keys beyond `confidence_threshold`.
- Changing the `usePreferences` hook interface.
