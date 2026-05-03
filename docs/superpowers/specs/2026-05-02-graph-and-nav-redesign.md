# Graph Panel + Nav Bar Redesign

## Overview

Three UI improvements to the NeuroNote workspace:

1. **Local graph panel simplification** — remove per-panel filter controls; use the global confidence threshold from user preferences. Remove the concept node list so the canvas fills the panel.
2. **Global graph view** — remove confidence slider and type checkboxes (same as local); add subject and tag filter dropdowns. Confidence and type are driven by global preference + hardcoded defaults.
3. **User avatar dropdown** — make the avatar in the top nav clickable, revealing a settings panel with: user identity, AI mode toggle, cloud API config (when Cloud selected), global confidence threshold slider, and sign out.

---

## Feature 1: Local Graph Panel Simplification

**`web/src/components/graph/LocalGraphPanel.tsx`**

- Remove the `filters` prop and `onFiltersChange` prop entirely.
- Remove all filter UI: depth `<select>`, confidence `<input type="range">`, type `<fieldset>` checkboxes.
- Remove the `handleIncludeTypeToggle` helper.
- Remove the `<ul className="local-graph-node-list">` and all its children.
- D3 canvas height: change from `height={300}` to `height={400}`.
- Keep the stats footer: `"{nodeCount} nodes · {edgeCount} edges"`.

**`web/src/components/editor/NoteEditor.tsx`**

- Add `confidenceThreshold?: number` prop (default `0.9`). `NotesWorkspace` passes `prefs?.confidence_threshold ?? 0.9` — same pattern as `llmMode`.
- Remove `localGraphFilters` state, `setLocalGraphFilters`, and the `DEFAULT_LOCAL_GRAPH_FILTERS` constant.
- Hardcode the graph fetch params: `{ max_hops: 1, limit_nodes: 80, min_confidence: confidenceThreshold ?? 0.9, include_types: ["note", "entity"] }`.
- Remove the `onFiltersChange` prop passed to `<LocalGraphPanel>`.

**`web/src/components/workspace/NotesWorkspace.tsx`**

- Pass `confidenceThreshold={prefs?.confidence_threshold ?? 0.9}` to `<NoteEditor>`. (`prefs` is already loaded via `usePreferences()` in `NotesWorkspace`.)
- Pass `confidenceThreshold={prefs?.confidence_threshold ?? 0.9}` to `useGlobalGraph()` — see Feature 2.

---

## Feature 2: Global Graph View — Subject/Tag Filters

The global graph sidebar currently has a confidence slider and type checkboxes. These are replaced with subject and tag dropdowns. Confidence comes from global preference; node types are hardcoded to `["note", "entity"]`.

### Backend

**`api/src/app/services/global_graph_service.py`**

Extend `GlobalGraphQuery`:
```python
@dataclass(frozen=True, slots=True)
class GlobalGraphQuery:
    limit_nodes: int
    min_confidence: float
    include_types: list[str]
    subject_id: str | None = None   # new
    tag: str | None = None           # new
```

In `get_global_graph()`, the notes query already does `select(Note.note_id, ...)`. Add optional WHERE clauses:
```python
stmt = select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
if query.subject_id:
    stmt = stmt.where(Note.subject_id == query.subject_id)
if query.tag:
    # Note has a many-to-many tags relationship via note_tags table
    stmt = stmt.where(Note.tags.any(Tag.name == query.tag))
```
Only notes matching the filter are included in the graph; entity/relation nodes connected only to excluded notes are dropped naturally by the existing build logic.

**`api/src/app/routes/graph.py`**

Add `subject_id` and `tag` query params to `get_global_graph`:
```python
@router.get("/graph/global", response_model=GlobalGraphResponse)
def get_global_graph(
    limit_nodes: int = Query(default=500, ge=1, le=2000),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    include_types: str = Query(default="note,entity,relation"),
    subject_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_tenant_session),
) -> GlobalGraphResponse:
    ...
    return GlobalGraphService(session).get_global_graph(
        GlobalGraphQuery(
            limit_nodes=limit_nodes,
            min_confidence=min_confidence,
            include_types=include_type_values,
            subject_id=subject_id,
            tag=tag,
        )
    )
```

**`shared/contracts/python/v1/graph.py`**

Add to `GlobalGraphFilters`:
```python
subject_id: str | None = None
tag: str | None = None
```

**`shared/contracts/ts/v1/graph.ts`**

Add to the matching `GlobalGraphFilters` interface:
```typescript
subject_id?: string;
tag?: string;
```

### Frontend

**`web/src/lib/api-client.ts`**

Extend `GlobalGraphQuery` interface and `fetchGlobalGraph`:
```typescript
interface GlobalGraphQuery {
  limit_nodes?: number;
  min_confidence?: number;
  include_types?: string[];
  subject_id?: string;   // new
  tag?: string;           // new
}
```
In `fetchGlobalGraph`, append the new params:
```typescript
if (query.subject_id) params.set("subject_id", query.subject_id);
if (query.tag) params.set("tag", query.tag);
```

**`web/src/lib/hooks/useGlobalGraph.ts`**

- Accept `confidenceThreshold: number` as a parameter: `useGlobalGraph(baseUrl, confidenceThreshold)`.
- Remove `min_confidence` from `GlobalGraphFilters`; add `subject_id?: string` and `tag?: string`.
- Update `DEFAULT_FILTERS` to `{ subject_id: undefined, tag: undefined }`.
- Pass `min_confidence: confidenceThreshold` and `include_types: ["note", "entity"]` as hardcoded values to `fetchGlobalGraph`; pass `subject_id` and `tag` from `filters`.

```typescript
export interface GlobalGraphFilters {
  subject_id?: string;
  tag?: string;
}

const DEFAULT_FILTERS: GlobalGraphFilters = {};

// hook signature:
export function useGlobalGraph(baseUrl: string, confidenceThreshold: number)
```

Inside `load()`:
```typescript
const response = await fetchGlobalGraph(baseUrl, {
  min_confidence: confidenceThreshold,
  include_types: ["note", "entity"],
  subject_id: filters.subject_id,
  tag: filters.tag,
});
```

**`web/src/components/graph/GlobalGraphPanel.tsx`**

- Add two props: `availableSubjects: string[]` and `availableTags: string[]`.
- Remove `min_confidence` and `include_types` from `GlobalGraphFilterState` (and from `onFiltersChange` type).
- Remove the confidence `<input type="range">` and `<fieldset>` type checkboxes from the sidebar.
- Add subject dropdown: `<select>` with an "All subjects" `<option value="">` plus one option per subject. On change: `onFiltersChange({ ...filters, subject_id: value || undefined })`.
- Add tag dropdown: same pattern. On change: `onFiltersChange({ ...filters, tag: value || undefined })`.

Updated `GlobalGraphFilterState`:
```typescript
export interface GlobalGraphFilterState {
  subject_id?: string;
  tag?: string;
}
```

**`web/src/components/workspace/NotesWorkspace.tsx`**

- Call `useGlobalGraph(baseUrl, prefs?.confidence_threshold ?? 0.9)` instead of `useGlobalGraph(baseUrl)`.
- Pass `availableSubjects={availableSubjects}` and `availableTags={availableTags}` to `<GlobalGraphPanel>`. (`availableSubjects` and `availableTags` are already computed via `useMemo` in `NotesWorkspace`.)

---

## Feature 3: User Avatar Dropdown

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

**Props**: `UserMenu` receives `user: UserProfile | null` (unchanged). Preferences are fetched internally via `usePreferences()`. This keeps the component self-contained.

**`web/src/components/workspace/NotesWorkspace.tsx`**

- Remove the existing `<LLMSettings>` modal and its open/close state.
- The `<UserMenu>` usage is unchanged — it already receives `user` prop.
- `WebGPUCheck`, `EdgeConsentDialog`, `EdgeCrashBanner` are unaffected.

**`web/src/components/settings/LLMSettings.tsx`** — delete. All functionality moves into UserMenu. Check for any other imports.

### Dropdown close behaviour

`useEffect` adds a `mousedown` listener to `document` when open; closes when click target is outside the dropdown wrapper ref. Cleaned up on unmount.

### State in UserMenu

```typescript
const [isOpen, setIsOpen] = useState(false);
const [cloudDraft, setCloudDraft] = useState({ llm_api_key: "", llm_base_url: "", llm_model: "" });
const [saving, setSaving] = useState(false);
```

`cloudDraft` is seeded from `prefs` when the dropdown opens so the user sees their current values.

---

## Confidence Threshold Preference (new key)

`confidence_threshold` (float, 0.5–1.0, default `0.9`) — stored in `user_preferences` per tenant.

**`shared/contracts/python/v1/preferences.py`**
```python
confidence_threshold: float = Field(default=0.9, ge=0.5, le=1.0)
# in UpdatePreferencesRequest:
confidence_threshold: float | None = None
```

**`shared/contracts/ts/v1/preferences.ts`**
```typescript
confidence_threshold: number;   // UserPreferences
confidence_threshold?: number;  // UpdatePreferencesRequest
```

**`api/src/app/routes/preferences.py`** — the existing PUT handler writes all non-null fields generically; no route logic changes needed. Verify and add key if handler is field-specific.

---

## CSS

New classes in `globals.css` (using existing token system):

- `.user-menu-wrapper` — `position: relative; display: inline-flex`
- `.user-menu-avatar-btn` — reset button styles, cursor pointer, border-radius 50%
- `.user-menu-dropdown` — `position: absolute; right: 0; top: calc(100% + 8px); background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 10px; box-shadow: var(--shadow-panel); min-width: 240px; z-index: var(--z-dropdown); overflow: hidden`
- `.user-menu-section` — `padding: 12px 14px; border-bottom: 1px solid var(--panel-border)`
- `.user-menu-label` — `font-size: var(--text-xs); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px`
- `.user-menu-mode-toggle` — `display: flex; border: 1px solid var(--panel-border); border-radius: 6px; overflow: hidden`
- `.user-menu-mode-btn` — pill within mode toggle; active: `background: var(--accent); color: #fff`
- `.user-menu-signout` — `padding: 8px 14px; font-size: var(--text-sm); color: var(--danger); cursor: pointer`

---

## Testing

**`web/src/components/auth/__tests__/UserMenu.test.tsx`** (new)

- Renders avatar button (image when `avatar_url` set; initials otherwise).
- Clicking avatar opens dropdown; Escape closes it; clicking outside closes it.
- AI mode toggle calls `updatePreferences` with correct `llm_mode`.
- Cloud config fields appear when Cloud mode is active; hidden when Edge mode is active.
- Save button calls `updatePreferences` with cloud config values.
- Confidence slider calls `updatePreferences` with `confidence_threshold` (use fake timers for debounce).
- Sign out button calls `logoutUser` and redirects.

**`web/src/components/graph/LocalGraphPanel.test.tsx`** (update)

- Remove tests referencing `onFiltersChange` or filter UI.
- Add: renders D3 canvas at height 400.
- Add: no filter controls rendered.
- Add: stats footer shows "N nodes · M edges".

**`web/src/components/graph/GlobalGraphPanel.test.tsx`** (new or update)

- Subject dropdown renders all options from `availableSubjects` + "All subjects".
- Selecting a subject calls `onFiltersChange` with correct `subject_id`.
- Tag dropdown same.
- No confidence slider or type checkboxes rendered.

**Backend** — `tests/integration/test_graph.py` (add cases):

- `GET /v1/graph/global?subject_id=physics` returns only nodes connected to notes with `subject_id="physics"`.
- `GET /v1/graph/global?tag=lecture` returns only nodes connected to tagged notes.
- Both filters together work correctly.

---

## Files Modified / Created

| File | Action |
|------|--------|
| `shared/contracts/python/v1/preferences.py` | Add `confidence_threshold` |
| `shared/contracts/ts/v1/preferences.ts` | Add `confidence_threshold` |
| `shared/contracts/python/v1/graph.py` | Add `subject_id`, `tag` to `GlobalGraphFilters` |
| `shared/contracts/ts/v1/graph.ts` | Add `subject_id`, `tag` to `GlobalGraphFilters` |
| `api/src/app/services/global_graph_service.py` | Add `subject_id`/`tag` to `GlobalGraphQuery`; filter notes query |
| `api/src/app/routes/graph.py` | Add `subject_id`/`tag` query params |
| `web/src/lib/api-client.ts` | Add `subject_id`/`tag` to `GlobalGraphQuery` |
| `web/src/lib/hooks/useGlobalGraph.ts` | Accept `confidenceThreshold` param; add subject/tag filters |
| `web/src/components/auth/UserMenu.tsx` | Rewrite as dropdown |
| `web/src/components/auth/__tests__/UserMenu.test.tsx` | Create |
| `web/src/components/graph/LocalGraphPanel.tsx` | Remove filters + node list; bigger canvas |
| `web/src/components/graph/LocalGraphPanel.test.tsx` | Update |
| `web/src/components/graph/GlobalGraphPanel.tsx` | Replace confidence+type with subject+tag dropdowns |
| `web/src/components/graph/GlobalGraphPanel.test.tsx` | Create or update |
| `web/src/components/editor/NoteEditor.tsx` | Remove filter state; use `confidenceThreshold` prop |
| `web/src/components/workspace/NotesWorkspace.tsx` | Pass `confidenceThreshold` + subject/tag lists to graph components; remove LLMSettings |
| `web/src/components/settings/LLMSettings.tsx` | Delete |
| `web/src/app/globals.css` | Add user-menu CSS classes |

---

## What is NOT in scope

- Landing page and onboarding tutorial — separate spec.
- Changing the graph layout algorithm or node colors.
- Adding more preference keys beyond `confidence_threshold`.
- Per-note subject/tag editing from within the graph view.
