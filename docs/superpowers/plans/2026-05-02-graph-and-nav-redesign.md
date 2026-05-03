# Graph Panel + Nav Bar Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify graph filter controls (global confidence threshold + subject/tag filters on global graph), and replace the static UserMenu with a clickable avatar dropdown containing inline AI mode toggle, cloud config, and confidence slider.

**Architecture:** Shared contracts gain `confidence_threshold` (preferences) and `subject_id`/`tag` (graph filters). Backend wires subject/tag into the global graph SQL query. Frontend components shed per-panel controls and read the single global threshold; `UserMenu` becomes a self-contained dropdown that writes preferences directly; `LLMSettings.tsx` is deleted.

**Tech Stack:** Python/FastAPI, SQLAlchemy, pytest (backend); TypeScript/React, Vitest/@testing-library/react (frontend).

---

## File Map

| File | Change |
|------|--------|
| `shared/contracts/python/v1/preferences.py` | Add `confidence_threshold` |
| `shared/contracts/ts/v1/preferences.ts` | Add `confidence_threshold` |
| `shared/contracts/python/v1/graph.py` | Add `subject_id`, `tag` to `GlobalGraphFilters` |
| `shared/contracts/ts/v1/graph.ts` | Add `subject_id`, `tag` to `GlobalGraphFilters` |
| `api/src/app/services/global_graph_service.py` | `GlobalGraphQuery` + `_list_notes` subject/tag filtering |
| `api/src/app/routes/graph.py` | Add `subject_id`/`tag` query params |
| `api/src/app/routes/preferences.py` | Add `confidence_threshold` to `_DEFAULTS` |
| `tests/integration/test_graph_api.py` | Add subject/tag filter tests |
| `web/src/lib/api-client.ts` | Add `subject_id`/`tag` to `GlobalGraphQuery` interface |
| `web/src/lib/hooks/useGlobalGraph.ts` | New `GlobalGraphFilters` type, `confidenceThreshold` param |
| `web/src/components/graph/LocalGraphPanel.tsx` | Remove all filters + node list, 400px canvas |
| `web/src/components/graph/LocalGraphPanel.test.tsx` | Update prop signatures and assertions |
| `web/src/components/editor/NoteEditor.tsx` | Add `confidenceThreshold` prop, remove filter state |
| `web/src/components/graph/GlobalGraphPanel.tsx` | Subject/tag dropdowns, remove confidence/type controls |
| `web/src/components/graph/GlobalGraphPanel.test.tsx` | New test file |
| `web/src/components/workspace/NotesWorkspace.tsx` | Wire all new props; remove LLMSettings/gear button |
| `web/src/components/auth/UserMenu.tsx` | Full rewrite as dropdown |
| `web/src/components/auth/__tests__/UserMenu.test.tsx` | New test file |
| `web/src/components/settings/LLMSettings.tsx` | Delete |
| `web/src/app/globals.css` | Add `.user-menu-*` CSS classes |

---

## Task 1: Shared contracts — confidence_threshold + global graph subject/tag

**Files:**
- Modify: `shared/contracts/python/v1/preferences.py`
- Modify: `shared/contracts/ts/v1/preferences.ts`
- Modify: `shared/contracts/python/v1/graph.py`
- Modify: `shared/contracts/ts/v1/graph.ts`

All changes are additive (new optional fields) so existing code remains valid.

- [ ] **Step 1: Update Python preferences contract**

In `shared/contracts/python/v1/preferences.py`, add `confidence_threshold` to both classes:

```python
class UserPreferences(BaseModel):
    """All user preferences as a flat dict."""

    llm_mode: str = Field(default="edge", pattern="^(edge|cloud)$")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini")
    confidence_threshold: float = Field(default=0.9, ge=0.5, le=1.0)


class UpdatePreferencesRequest(BaseModel):
    """Partial update — only provided fields are written."""

    llm_mode: str | None = Field(default=None, pattern="^(edge|cloud)$")
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.5, le=1.0)
```

- [ ] **Step 2: Update TypeScript preferences contract**

In `shared/contracts/ts/v1/preferences.ts`, replace the file content with:

```typescript
/** All user preferences as a flat object. */
export interface UserPreferences {
  llm_mode: "edge" | "cloud";
  llm_api_key: string;
  llm_base_url: string;
  llm_model: string;
  confidence_threshold: number;
}

/** Partial update — only provided fields are written. */
export interface UpdatePreferencesRequest {
  llm_mode?: "edge" | "cloud";
  llm_api_key?: string;
  llm_base_url?: string;
  llm_model?: string;
  confidence_threshold?: number;
}

/** Result of a test LLM connection attempt. */
export interface TestConnectionResponse {
  success: boolean;
  message: string;
}
```

- [ ] **Step 3: Update Python graph contract**

In `shared/contracts/python/v1/graph.py`, add `subject_id` and `tag` to `GlobalGraphFilters`:

```python
class GlobalGraphFilters(BaseModel):
    limit_nodes: int = Field(ge=1, le=2000)
    min_confidence: float = Field(ge=0.0, le=1.0)
    include_types: list[str] = Field(default_factory=list)
    subject_id: str | None = None
    tag: str | None = None
```

- [ ] **Step 4: Update TypeScript graph contract**

In `shared/contracts/ts/v1/graph.ts`, update `GlobalGraphFilters`:

```typescript
export interface GlobalGraphFilters {
  limit_nodes: number;
  min_confidence: number;
  include_types: string[];
  subject_id?: string;
  tag?: string;
}
```

- [ ] **Step 5: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add shared/contracts/python/v1/preferences.py shared/contracts/ts/v1/preferences.ts \
        shared/contracts/python/v1/graph.py shared/contracts/ts/v1/graph.ts
git commit -m "feat: add confidence_threshold to preferences + subject/tag to graph filters contracts"
```

---

## Task 2: Backend — global graph subject/tag filtering + preferences default

**Files:**
- Modify: `api/src/app/services/global_graph_service.py`
- Modify: `api/src/app/routes/graph.py`
- Modify: `api/src/app/routes/preferences.py`
- Test: `tests/integration/test_graph_api.py`

- [ ] **Step 1: Write failing integration tests**

Append to `tests/integration/test_graph_api.py`:

```python
def test_global_graph_filters_by_subject_id(client: TestClient) -> None:
    client.put(
        "/v1/notes/subj-physics-1",
        json={**_payload("subj-physics-1", "Physics Note", "Newton laws", "2026-05-02T10:00:00Z"),
              "subject_id": "physics"},
    )
    client.put(
        "/v1/notes/subj-math-1",
        json={**_payload("subj-math-1", "Math Note", "Calculus derivatives", "2026-05-02T10:01:00Z"),
              "subject_id": "math"},
    )

    resp = client.get("/v1/graph/global", params={"subject_id": "physics", "include_types": "note"})
    assert resp.status_code == 200
    body = resp.json()
    note_ids = {n["id"] for n in body["nodes"]}
    assert "subj-physics-1" in note_ids
    assert "subj-math-1" not in note_ids
    assert body["meta"]["applied_filters"]["subject_id"] == "physics"


def test_global_graph_filters_by_tag(client: TestClient) -> None:
    client.put(
        "/v1/notes/tag-lecture-1",
        json={**_payload("tag-lecture-1", "Lecture Note", "Today we covered photosynthesis", "2026-05-02T11:00:00Z"),
              "tags": ["lecture"]},
    )
    client.put(
        "/v1/notes/tag-notag-1",
        json=_payload("tag-notag-1", "Untagged Note", "Some content", "2026-05-02T11:01:00Z"),
    )

    resp = client.get("/v1/graph/global", params={"tag": "lecture", "include_types": "note"})
    assert resp.status_code == 200
    body = resp.json()
    note_ids = {n["id"] for n in body["nodes"]}
    assert "tag-lecture-1" in note_ids
    assert "tag-notag-1" not in note_ids
    assert body["meta"]["applied_filters"]["tag"] == "lecture"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make compose-test
```
Expected: the two new test functions fail because `subject_id` / `tag` are not yet accepted.

- [ ] **Step 3: Add subject/tag to GlobalGraphQuery dataclass**

In `api/src/app/services/global_graph_service.py`, replace the `GlobalGraphQuery` dataclass:

```python
@dataclass(frozen=True, slots=True)
class GlobalGraphQuery:
    limit_nodes: int
    min_confidence: float
    include_types: list[str]
    subject_id: str | None = None
    tag: str | None = None
```

Also add imports at the top of the file (after the existing imports):
```python
from app.db.models.note_tag import NoteTag
from app.db.models.tag import Tag
```

- [ ] **Step 4: Update _list_notes to filter by subject/tag**

In `global_graph_service.py`, replace `_list_notes`:

```python
def _list_notes(
    self,
    *,
    limit: int,
    subject_id: str | None = None,
    tag: str | None = None,
) -> list[_NoteSnapshot]:
    stmt = (
        select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
        .order_by(desc(Note.updated_at))
        .limit(limit)
    )
    if subject_id:
        stmt = stmt.where(Note.subject_id == subject_id)
    if tag:
        stmt = stmt.where(
            Note.note_id.in_(
                select(NoteTag.note_id)
                .join(Tag, NoteTag.tag_id == Tag.id)
                .where(Tag.name == tag)
            )
        )
    rows = self._session.execute(stmt).all()

    note_ids = [str(row[0]) for row in rows]
    block_rows = self._session.execute(
        select(Block.note_id, Block.block_index, Block.content_text)
        .where(Block.note_id.in_(note_ids))
        .order_by(Block.note_id.asc(), Block.block_index.asc())
    ).all()
    blocks_by_note_id: dict[str, list[BlockTextInput]] = {}
    for row in block_rows:
        blocks_by_note_id.setdefault(str(row[0]), []).append(
            BlockTextInput(
                block_index=int(row[1]),
                content_text=str(row[2]),
            )
        )

    return [
        _NoteSnapshot(
            note_id=str(row[0]),
            note_title=str(row[1]),
            content_text=str(row[2]),
            subject_id=str(row[3]) if row[3] else "inbox",
            blocks=list(blocks_by_note_id.get(str(row[0]), [])),
        )
        for row in rows
    ]
```

- [ ] **Step 5: Update get_global_graph to pass filters + include in cache key + applied_filters**

In `get_global_graph`, make three changes:

**a) Update cache key** (replace the existing `cache_key = ...` lines):
```python
cache_key = (
    f"global:{query.limit_nodes}:{query.min_confidence}"
    f":{'|'.join(sorted(include_types))}"
    f":{query.subject_id or ''}:{query.tag or ''}:{notes_version}"
)
```

**b) Update `_list_notes` call** (replace `notes = self._list_notes(limit=query.limit_nodes * 2)`):
```python
notes = self._list_notes(
    limit=query.limit_nodes * 2,
    subject_id=query.subject_id,
    tag=query.tag,
)
```

**c) Update `GlobalGraphFilters` construction** in the `response = GlobalGraphResponse(...)` block:
```python
applied_filters=GlobalGraphFilters(
    limit_nodes=query.limit_nodes,
    min_confidence=query.min_confidence,
    include_types=include_types,
    subject_id=query.subject_id,
    tag=query.tag,
),
```

- [ ] **Step 6: Add subject_id/tag query params to the route**

In `api/src/app/routes/graph.py`, replace `get_global_graph`:

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
    include_type_values = [item.strip() for item in include_types.split(",") if item.strip()]
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

- [ ] **Step 7: Add confidence_threshold to preferences _DEFAULTS**

In `api/src/app/routes/preferences.py`, update `_DEFAULTS`:

```python
_DEFAULTS: dict[str, str] = {
    "llm_mode": "edge",
    "llm_api_key": "",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "confidence_threshold": "0.9",
}
```

Note: `UserPreferences` is a Pydantic model — when `UserPreferences(**prefs)` is called, the `confidence_threshold` value `"0.9"` (a string from the DB) is coerced to `float` by the `confidence_threshold: float` field declaration. This works because Pydantic v2 coerces compatible types.

- [ ] **Step 8: Run tests to verify they pass**

```bash
make compose-test
```
Expected: all tests pass including the two new ones.

- [ ] **Step 9: Commit**

```bash
git add api/src/app/services/global_graph_service.py \
        api/src/app/routes/graph.py \
        api/src/app/routes/preferences.py \
        tests/integration/test_graph_api.py
git commit -m "feat: add subject/tag filtering to global graph + confidence_threshold preference default"
```

---

## Task 3: Frontend API client — subject/tag in fetchGlobalGraph

**Files:**
- Modify: `web/src/lib/api-client.ts`

- [ ] **Step 1: Update GlobalGraphQuery interface and fetchGlobalGraph**

In `web/src/lib/api-client.ts`, find the `GlobalGraphQuery` interface (around line 362) and replace it plus the `fetchGlobalGraph` function:

```typescript
interface GlobalGraphQuery {
  limit_nodes?: number;
  min_confidence?: number;
  include_types?: string[];
  subject_id?: string;
  tag?: string;
}

export async function fetchGlobalGraph(
  baseUrl: string,
  query: GlobalGraphQuery = {},
): Promise<GlobalGraphResponse> {
  const params = new URLSearchParams();
  if (query.limit_nodes !== undefined) params.set("limit_nodes", String(query.limit_nodes));
  if (query.min_confidence !== undefined) params.set("min_confidence", String(query.min_confidence));
  if (query.include_types && query.include_types.length > 0) params.set("include_types", query.include_types.join(","));
  if (query.subject_id) params.set("subject_id", query.subject_id);
  if (query.tag) params.set("tag", query.tag);
  const suffix = params.toString();
  const response = await apiFetch(
    `${baseUrl}/v1/graph/global${suffix ? `?${suffix}` : ""}`,
    { timeoutMs: 60_000 },
  );
  return parseJsonResponse<GlobalGraphResponse>(response);
}
```

- [ ] **Step 2: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/api-client.ts
git commit -m "feat: add subject_id/tag params to fetchGlobalGraph"
```

---

## Task 4: LocalGraphPanel simplification + NoteEditor confidenceThreshold prop

**Files:**
- Modify: `web/src/components/graph/LocalGraphPanel.tsx`
- Modify: `web/src/components/graph/LocalGraphPanel.test.tsx`
- Modify: `web/src/components/editor/NoteEditor.tsx`

- [ ] **Step 1: Update LocalGraphPanel tests first**

Replace `web/src/components/graph/LocalGraphPanel.test.tsx` entirely:

```typescript
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LocalGraphPanel } from "./LocalGraphPanel";

describe("LocalGraphPanel", () => {
  it("renders loading state", () => {
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={null}
        isLoading
        errorMessage={null}
        onRetry={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(document.querySelector(".skeleton-graph")).toBeInTheDocument();
  });

  it("renders error state and retries", () => {
    const onRetry = vi.fn();
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={null}
        isLoading={false}
        errorMessage="Failed to load local graph"
        onRetry={onRetry}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders graph canvas and stats footer without filter controls", () => {
    render(
      <LocalGraphPanel
        noteId="note-1"
        baseUrl="http://localhost:8000"
        graph={{
          nodes: [
            { id: "note-1", type: "note", label: "Note 1", confidence: null, source_note_id: "note-1", metadata: {} },
            { id: "note-2", type: "note", label: "Note 2", confidence: null, source_note_id: "note-2", metadata: {} },
          ],
          edges: [
            { id: "edge-1", source: "note-1", target: "note-2", type: "LINKS_TO", confidence: 1, source_note_id: "note-1" },
          ],
          meta: {
            root_note_id: "note-1",
            applied_filters: { max_hops: 1, limit_nodes: 80, min_confidence: 0.9, include_types: ["note", "entity"] },
            truncated: false,
          },
        }}
        isLoading={false}
        errorMessage={null}
        onRetry={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(screen.getByLabelText("Local graph canvas")).toBeInTheDocument();
    expect(screen.getByText("2 nodes · 1 edges")).toBeInTheDocument();
    // No filter controls
    expect(screen.queryByLabelText("Graph depth")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Minimum confidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox", { name: "Local graph nodes" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd web && npm run test
```
Expected: tests referencing removed props/elements will fail because the component still has them.

- [ ] **Step 3: Rewrite LocalGraphPanel**

Replace `web/src/components/graph/LocalGraphPanel.tsx` entirely:

```typescript
"use client";

import { useState } from "react";

import { D3GraphCanvas } from "./D3GraphCanvas";
import { ConceptInsightPanel } from "./ConceptInsightPanel";
import type { LocalGraphNode, LocalGraphResponse } from "../../../../shared/contracts/ts/v1/graph";
import { SkeletonGraph } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ErrorMessage } from "../ui/ErrorMessage";

interface LocalGraphPanelProps {
  noteId: string;
  baseUrl: string;
  graph: LocalGraphResponse | null;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onOpenNote: (noteId: string) => void;
}

export function LocalGraphPanel({
  noteId,
  baseUrl,
  graph,
  isLoading,
  errorMessage,
  onRetry,
  onOpenNote,
}: LocalGraphPanelProps) {
  const [insightNode, setInsightNode] = useState<LocalGraphNode | null>(null);

  function handleNodeClick(node: LocalGraphNode) {
    if (node.type === "note") {
      onOpenNote(String(node.metadata.note_id ?? node.id));
    } else {
      setInsightNode(node);
    }
  }

  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;

  if (isLoading) {
    return <SkeletonGraph />;
  }

  if (errorMessage) {
    return (
      <ErrorMessage
        message={errorMessage}
        actionLabel="Retry"
        onAction={onRetry}
      />
    );
  }

  return (
    <section className="local-graph-panel" aria-label="Local graph panel">
      <header className="local-graph-header">
        <h2>Local graph</h2>
      </header>

      {graph !== null && (
        <>
          {nodeCount === 0 ? (
            <EmptyState
              icon="🕸️"
              title="No connections yet"
              description="Add wiki links or process this note to discover relationships."
            />
          ) : (
            <D3GraphCanvas
              nodes={graph.nodes}
              edges={graph.edges}
              rootNodeId={noteId}
              height={400}
              ariaLabel="Local graph canvas"
              onNodeClick={handleNodeClick}
            />
          )}
        </>
      )}

      <div className="local-graph-summary">
        <p>{nodeCount} nodes · {edgeCount} edges</p>
      </div>

      {insightNode && (
        <ConceptInsightPanel
          node={insightNode}
          baseUrl={baseUrl}
          onClose={() => setInsightNode(null)}
          onOpenNote={onOpenNote}
        />
      )}
    </section>
  );
}
```

- [ ] **Step 4: Update NoteEditor to remove filter state and add confidenceThreshold prop**

In `web/src/components/editor/NoteEditor.tsx`:

**a)** Delete the `DEFAULT_LOCAL_GRAPH_FILTERS` constant (lines around 241–246).

**b)** Add `confidenceThreshold?: number` to the `NoteEditorProps` interface, after the `llmMode` prop:
```typescript
confidenceThreshold?: number;
```

**c)** Add `confidenceThreshold = 0.9` to the destructured props (after `llmMode`):
```typescript
confidenceThreshold = 0.9,
```

**d)** Remove the `localGraphFilters` state declaration and `setLocalGraphFilters`:
```typescript
// DELETE this line:
const [localGraphFilters, setLocalGraphFilters] = useState({ ...DEFAULT_LOCAL_GRAPH_FILTERS, include_types: [...DEFAULT_LOCAL_GRAPH_FILTERS.include_types] });
```

**e)** In the `loadLocalGraph` callback, replace the `fetchLocalGraph(baseUrl, noteId, localGraphFilters)` call:
```typescript
const result = await fetchLocalGraph(baseUrl, noteId, {
  max_hops: 1,
  limit_nodes: 80,
  min_confidence: confidenceThreshold,
  include_types: ["note", "entity"],
});
```

**f)** Remove `localGraphFilters` from the `useCallback` dependency array of `loadLocalGraph` — it no longer exists. The dependency array should be:
```typescript
}, [baseUrl, noteId, confidenceThreshold]);
```

**g)** In the `<LocalGraphPanel>` JSX (around line 862), remove the `filters` and `onFiltersChange` props:
```tsx
<LocalGraphPanel
  noteId={noteId}
  baseUrl={baseUrl}
  graph={localGraph}
  isLoading={localGraphLoading}
  errorMessage={localGraphErrorMessage}
  onRetry={() => { void loadLocalGraph(); }}
  onOpenNote={(nextNoteId) => { onOpenNote?.(nextNoteId); }}
/>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd web && npm run test
```
Expected: all tests pass.

- [ ] **Step 6: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/graph/LocalGraphPanel.tsx \
        web/src/components/graph/LocalGraphPanel.test.tsx \
        web/src/components/editor/NoteEditor.tsx
git commit -m "feat: simplify LocalGraphPanel (remove filters/node-list, 400px canvas)"
```

---

## Task 5: useGlobalGraph hook + GlobalGraphPanel subject/tag redesign + NotesWorkspace wiring

**Files:**
- Modify: `web/src/lib/hooks/useGlobalGraph.ts`
- Modify: `web/src/components/graph/GlobalGraphPanel.tsx`
- Create: `web/src/components/graph/GlobalGraphPanel.test.tsx`
- Modify: `web/src/components/workspace/NotesWorkspace.tsx`

- [ ] **Step 1: Create failing GlobalGraphPanel tests**

Create `web/src/components/graph/GlobalGraphPanel.test.tsx`:

```typescript
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GlobalGraphPanel } from "./GlobalGraphPanel";

const emptyGraph = {
  nodes: [],
  edges: [],
  meta: {
    total_notes: 0,
    applied_filters: { limit_nodes: 500, min_confidence: 0.9, include_types: ["note", "entity"] },
    truncated: false,
  },
};

describe("GlobalGraphPanel", () => {
  it("renders subject dropdown with all options and default empty selection", () => {
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={["math", "physics"]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    const select = screen.getByLabelText("Filter by subject") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByText("All subjects")).toBeInTheDocument();
    expect(screen.getByText("math")).toBeInTheDocument();
    expect(screen.getByText("physics")).toBeInTheDocument();
  });

  it("calls onFiltersChange with subject_id when subject is selected", () => {
    const onFiltersChange = vi.fn();
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={["math", "physics"]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={onFiltersChange}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Filter by subject"), { target: { value: "math" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ subject_id: "math" });
  });

  it("renders tag dropdown and calls onFiltersChange when tag selected", () => {
    const onFiltersChange = vi.fn();
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={["lecture", "research"]}
        onRetry={() => {}}
        onFiltersChange={onFiltersChange}
        onOpenNote={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Filter by tag"), { target: { value: "lecture" } });
    expect(onFiltersChange).toHaveBeenCalledWith({ tag: "lecture" });
  });

  it("does not render confidence slider or type checkboxes", () => {
    render(
      <GlobalGraphPanel
        baseUrl="http://localhost:8000"
        graph={emptyGraph}
        filters={{}}
        isLoading={false}
        errorMessage={null}
        availableSubjects={[]}
        availableTags={[]}
        onRetry={() => {}}
        onFiltersChange={() => {}}
        onOpenNote={() => {}}
      />,
    );
    expect(screen.queryByLabelText("Minimum confidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Include")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd web && npm run test
```
Expected: all 4 new GlobalGraphPanel tests fail — component still has old shape.

- [ ] **Step 3: Update useGlobalGraph hook**

Replace `web/src/lib/hooks/useGlobalGraph.ts` entirely:

```typescript
import { useCallback, useRef, useState } from "react";
import { fetchGlobalGraph } from "../api-client";
import type { GlobalGraphResponse } from "../../../../shared/contracts/ts/v1/graph";

export interface GlobalGraphFilters {
  subject_id?: string;
  tag?: string;
}

const DEFAULT_FILTERS: GlobalGraphFilters = {};

export interface UseGlobalGraphState {
  graph: GlobalGraphResponse | null;
  isLoading: boolean;
  errorMessage: string | null;
  filters: GlobalGraphFilters;
}

export interface UseGlobalGraphActions {
  load: () => void;
  setFilters: (filters: GlobalGraphFilters) => void;
}

export function useGlobalGraph(
  baseUrl: string,
  confidenceThreshold: number = 0.9,
): UseGlobalGraphState & UseGlobalGraphActions {
  const [graph, setGraph] = useState<GlobalGraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [filters, setFilters] = useState<GlobalGraphFilters>(DEFAULT_FILTERS);
  const requestTokenRef = useRef(0);

  const load = useCallback(async () => {
    const token = requestTokenRef.current + 1;
    requestTokenRef.current = token;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const response = await fetchGlobalGraph(baseUrl, {
        min_confidence: confidenceThreshold,
        include_types: ["note", "entity"],
        subject_id: filters.subject_id,
        tag: filters.tag,
      });
      if (requestTokenRef.current !== token) return;
      setGraph(response);
    } catch {
      if (requestTokenRef.current !== token) return;
      setGraph(null);
      setErrorMessage("Failed to load global graph");
    } finally {
      if (requestTokenRef.current === token) {
        setIsLoading(false);
      }
    }
  }, [baseUrl, confidenceThreshold, filters]);

  return { graph, isLoading, errorMessage, filters, load, setFilters };
}
```

- [ ] **Step 4: Rewrite GlobalGraphPanel**

Replace `web/src/components/graph/GlobalGraphPanel.tsx` entirely:

```typescript
"use client";

import { useEffect, useRef, useState } from "react";

import { D3GraphCanvas } from "./D3GraphCanvas";
import { ConceptInsightPanel } from "./ConceptInsightPanel";
import type { GlobalGraphResponse, LocalGraphNode } from "../../../../shared/contracts/ts/v1/graph";
import { SkeletonGraph } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { ErrorMessage } from "../ui/ErrorMessage";
import type { GlobalGraphFilters } from "../../lib/hooks/useGlobalGraph";

export type { GlobalGraphFilters };

interface GlobalGraphPanelProps {
  baseUrl: string;
  graph: GlobalGraphResponse | null;
  filters: GlobalGraphFilters;
  isLoading: boolean;
  errorMessage: string | null;
  availableSubjects: string[];
  availableTags: string[];
  onRetry: () => void;
  onFiltersChange: (next: GlobalGraphFilters) => void;
  onOpenNote: (noteId: string) => void;
}

export function GlobalGraphPanel({
  baseUrl,
  graph,
  filters,
  isLoading,
  errorMessage,
  availableSubjects,
  availableTags,
  onRetry,
  onFiltersChange,
  onOpenNote,
}: GlobalGraphPanelProps) {
  const [insightNode, setInsightNode] = useState<LocalGraphNode | null>(null);
  const [nodeSearch, setNodeSearch] = useState("");
  const [canvasWidth, setCanvasWidth] = useState(800);
  const [canvasHeight, setCanvasHeight] = useState(600);
  const canvasAreaRef = useRef<HTMLDivElement>(null);

  function handleNodeClick(node: LocalGraphNode) {
    if (node.type === "note") {
      onOpenNote(String(node.metadata.note_id ?? node.id));
    } else {
      setInsightNode(node);
    }
  }

  useEffect(() => {
    const el = canvasAreaRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      if (rect.width > 0) setCanvasWidth(rect.width);
      if (rect.height > 0) setCanvasHeight(rect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const normalizedSearch = nodeSearch.trim().toLowerCase();
  const highlightNodeId = normalizedSearch && graph
    ? graph.nodes.find((n) => n.label.toLowerCase().includes(normalizedSearch))?.id
    : undefined;

  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;

  return (
    <div className="global-graph-view" aria-label="Global graph view">
      <aside className="global-graph-sidebar">
        <h2>Knowledge Graph</h2>
        <input
          className="notes-filter-input"
          type="text"
          aria-label="Search nodes"
          placeholder="Search nodes…"
          value={nodeSearch}
          onChange={(e) => setNodeSearch(e.target.value)}
        />

        <div className="local-graph-filters">
          <label className="notes-filter-label">
            Subject
            <select
              className="notes-filter-input"
              aria-label="Filter by subject"
              value={filters.subject_id ?? ""}
              onChange={(e) => onFiltersChange({ ...filters, subject_id: e.target.value || undefined })}
            >
              <option value="">All subjects</option>
              {availableSubjects.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <label className="notes-filter-label">
            Tag
            <select
              className="notes-filter-input"
              aria-label="Filter by tag"
              value={filters.tag ?? ""}
              onChange={(e) => onFiltersChange({ ...filters, tag: e.target.value || undefined })}
            >
              <option value="">All tags</option>
              {availableTags.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="local-graph-summary">
          <p>{nodeCount} nodes</p>
          <p>{edgeCount} edges</p>
        </div>
        {graph?.meta.truncated && (
          <p className="global-graph-truncated-note">
            Showing top {graph.meta.applied_filters.limit_nodes} nodes
          </p>
        )}
      </aside>

      <div className="global-graph-canvas-area" ref={canvasAreaRef}>
        {isLoading ? (
          <SkeletonGraph />
        ) : errorMessage ? (
          <ErrorMessage message={errorMessage} actionLabel="Retry" onAction={onRetry} />
        ) : !graph || nodeCount === 0 ? (
          <EmptyState
            icon="🕸️"
            title="No notes yet"
            description="Start creating notes to see your knowledge graph."
          />
        ) : (
          <D3GraphCanvas
            nodes={graph.nodes}
            edges={graph.edges}
            highlightNodeId={highlightNodeId}
            width={canvasWidth}
            height={canvasHeight}
            onNodeClick={handleNodeClick}
          />
        )}
      </div>

      {insightNode && (
        <ConceptInsightPanel
          node={insightNode}
          baseUrl={baseUrl}
          onClose={() => setInsightNode(null)}
          onOpenNote={(noteId) => {
            onOpenNote(noteId);
            setInsightNode(null);
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: Update NotesWorkspace for global graph wiring**

In `web/src/components/workspace/NotesWorkspace.tsx`:

**a)** Find the `useGlobalGraph` call (search for `useGlobalGraph(baseUrl)`) and update it to pass the confidence threshold:
```typescript
const globalGraph = useGlobalGraph(baseUrl, prefs?.confidence_threshold ?? 0.9);
```

**b)** Find the `<GlobalGraphPanel>` JSX (around line 1147) and add the two new props:
```tsx
<GlobalGraphPanel
  baseUrl={baseUrl}
  graph={globalGraph.graph}
  filters={globalGraph.filters}
  isLoading={globalGraph.isLoading}
  errorMessage={globalGraph.errorMessage}
  availableSubjects={availableSubjects}
  availableTags={availableTags}
  onRetry={() => { void globalGraph.load(); }}
  onFiltersChange={(next) => { globalGraph.setFilters(next); }}
  onOpenNote={(nextNoteId) => {
    if (!notes.some((item) => item.note_id === nextNoteId)) return;
    setAppView("notes");
    setSelectedNoteId(nextNoteId);
    setHighlightedNoteId(nextNoteId);
  }}
/>
```

**c)** Find the `<NoteEditor>` JSX and add the `confidenceThreshold` prop. Search for `llmMode={prefs?.llm_mode ?? "edge"}` and add the next line:
```tsx
confidenceThreshold={prefs?.confidence_threshold ?? 0.9}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd web && npm run test
```
Expected: all tests pass including the 4 new GlobalGraphPanel tests.

- [ ] **Step 7: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/hooks/useGlobalGraph.ts \
        web/src/components/graph/GlobalGraphPanel.tsx \
        web/src/components/graph/GlobalGraphPanel.test.tsx \
        web/src/components/workspace/NotesWorkspace.tsx
git commit -m "feat: global graph subject/tag filters; confidence threshold from preferences"
```

---

## Task 6: UserMenu dropdown rewrite + CSS + tests

**Files:**
- Modify: `web/src/app/globals.css`
- Modify: `web/src/components/auth/UserMenu.tsx`
- Create: `web/src/components/auth/__tests__/UserMenu.test.tsx`

- [ ] **Step 1: Add user-menu CSS classes to globals.css**

Append to the end of `web/src/app/globals.css`:

```css
/* ── User menu dropdown ──────────────────────────────────────────── */

.user-menu-wrapper {
  position: relative;
  display: inline-flex;
}

.user-menu-avatar-btn {
  all: unset;
  cursor: pointer;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-menu-avatar-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.user-menu-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-panel);
  min-width: 240px;
  z-index: var(--z-dropdown);
  overflow: hidden;
}

.user-menu-section {
  padding: 12px 14px;
  border-bottom: 1px solid var(--panel-border);
}

.user-menu-section:last-child {
  border-bottom: none;
}

.user-menu-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-weight: var(--font-semibold);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}

.user-menu-mode-toggle {
  display: flex;
  border: 1px solid var(--panel-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.user-menu-mode-btn {
  all: unset;
  flex: 1;
  padding: 6px 10px;
  font-size: var(--text-xs);
  text-align: center;
  cursor: pointer;
  color: var(--text-muted);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.user-menu-mode-btn.active {
  background: var(--accent);
  color: #fff;
  font-weight: var(--font-semibold);
}

.user-menu-cloud-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}

.user-menu-signout-btn {
  all: unset;
  display: block;
  width: 100%;
  padding: 10px 14px;
  font-size: var(--text-sm);
  color: var(--danger);
  cursor: pointer;
  box-sizing: border-box;
}

.user-menu-signout-btn:hover {
  background: var(--workspace-bg);
}
```

- [ ] **Step 2: Write failing UserMenu tests**

Create `web/src/components/auth/__tests__/UserMenu.test.tsx`:

```typescript
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";

// Mock api-client before importing component
vi.mock("../../../lib/api-client", () => ({
  logoutUser: vi.fn().mockResolvedValue(undefined),
  updatePreferences: vi.fn().mockResolvedValue({
    llm_mode: "edge",
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
    confidence_threshold: 0.9,
  }),
  fetchPreferences: vi.fn().mockResolvedValue({
    llm_mode: "edge",
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
    confidence_threshold: 0.9,
  }),
}));

import { UserMenu } from "../UserMenu";
import { updatePreferences, logoutUser } from "../../../lib/api-client";

const mockUser = {
  id: "user-1",
  email: "test@example.com",
  display_name: "Test User",
  avatar_url: null,
  schema_name: "user_abc",
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: "2026-01-01T00:00:00Z",
};

describe("UserMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders avatar button with initials when no avatar_url", () => {
    render(<UserMenu user={mockUser} />);
    expect(screen.getByRole("button", { name: "Open settings" })).toBeInTheDocument();
    expect(screen.getByText("TU")).toBeInTheDocument();
  });

  it("renders avatar img when avatar_url is set", () => {
    render(<UserMenu user={{ ...mockUser, avatar_url: "https://example.com/avatar.jpg" }} />);
    const img = screen.getByRole("img", { name: "Test User" });
    expect(img).toBeInTheDocument();
  });

  it("opens dropdown when avatar button is clicked", async () => {
    render(<UserMenu user={mockUser} />);
    expect(screen.queryByText("test@example.com")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => expect(screen.getByText("test@example.com")).toBeInTheDocument());
  });

  it("closes dropdown when Escape is pressed", async () => {
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => expect(screen.getByText("test@example.com")).toBeInTheDocument());
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("test@example.com")).not.toBeInTheDocument());
  });

  it("calls updatePreferences with llm_mode cloud when Cloud AI pill clicked", async () => {
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByRole("button", { name: "Cloud AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Cloud AI" }));
    await waitFor(() =>
      expect(updatePreferences).toHaveBeenCalledWith(expect.objectContaining({ llm_mode: "cloud" }))
    );
  });

  it("shows cloud config fields when Cloud AI mode is active", async () => {
    vi.mocked(fetchPreferences).mockResolvedValue({
      llm_mode: "cloud",
      llm_api_key: "****abcd",
      llm_base_url: "https://api.openai.com/v1",
      llm_model: "gpt-4o-mini",
      confidence_threshold: 0.9,
    });
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByPlaceholderText(/API Key/i));
    expect(screen.getByPlaceholderText(/Base URL/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Model/i)).toBeInTheDocument();
  });

  it("calls logoutUser and redirects on sign out", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "" },
    });
    render(<UserMenu user={mockUser} />);
    fireEvent.click(screen.getByRole("button", { name: "Open settings" }));
    await waitFor(() => screen.getByRole("button", { name: /sign out/i }));
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => expect(logoutUser).toHaveBeenCalledTimes(1));
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd web && npm run test
```
Expected: UserMenu tests fail — component is not yet rewritten.

- [ ] **Step 4: Rewrite UserMenu**

Replace `web/src/components/auth/UserMenu.tsx` entirely:

```typescript
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { logoutUser, updatePreferences } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";
import type { UserProfile } from "../../../../shared/contracts/ts/v1/auth";

interface UserMenuProps {
  user: UserProfile | null;
}

function getInitials(displayName: string | null, email: string): string {
  const source = displayName || email.split("@")[0] || "?";
  const parts = source.trim().split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

export function UserMenu({ user }: UserMenuProps) {
  const { prefs, reload } = usePreferences();
  const [isOpen, setIsOpen] = useState(false);
  const [cloudDraft, setCloudDraft] = useState({
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
  });
  const [saving, setSaving] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const confidenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Seed cloud draft when dropdown opens
  useEffect(() => {
    if (isOpen && prefs) {
      setCloudDraft({
        llm_api_key: "",
        llm_base_url: prefs.llm_base_url,
        llm_model: prefs.llm_model,
      });
    }
  }, [isOpen, prefs]);

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;
    const handleMouseDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [isOpen]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  const handleModeChange = useCallback(async (mode: "edge" | "cloud") => {
    await updatePreferences({ llm_mode: mode });
    void reload();
  }, [reload]);

  const handleCloudSave = useCallback(async () => {
    setSaving(true);
    try {
      await updatePreferences({
        llm_api_key: cloudDraft.llm_api_key || undefined,
        llm_base_url: cloudDraft.llm_base_url,
        llm_model: cloudDraft.llm_model,
      });
      void reload();
    } finally {
      setSaving(false);
    }
  }, [cloudDraft, reload]);

  const handleConfidenceChange = useCallback((value: number) => {
    if (confidenceTimerRef.current) clearTimeout(confidenceTimerRef.current);
    confidenceTimerRef.current = setTimeout(() => {
      void updatePreferences({ confidence_threshold: value }).then(() => reload());
    }, 500);
  }, [reload]);

  const handleLogout = useCallback(async () => {
    await logoutUser();
    window.location.href = "/login";
  }, []);

  if (!user) return null;

  const initials = getInitials(user.display_name, user.email);
  const label = user.display_name || user.email;
  const llmMode = prefs?.llm_mode ?? "edge";
  const confidenceThreshold = prefs?.confidence_threshold ?? 0.9;

  return (
    <div className="user-menu-wrapper" ref={wrapperRef}>
      <button
        type="button"
        className="user-menu-avatar-btn"
        aria-label="Open settings"
        aria-expanded={isOpen}
        aria-haspopup="true"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        {user.avatar_url ? (
          <img
            src={user.avatar_url}
            alt={label}
            style={{ width: "28px", height: "28px", borderRadius: "50%", objectFit: "cover" }}
          />
        ) : (
          <span
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "50%",
              background: "var(--accent)",
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "var(--text-xs)",
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {initials}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="user-menu-dropdown">
          {/* User identity */}
          <div className="user-menu-section" style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={label}
                style={{ width: "32px", height: "32px", borderRadius: "50%", objectFit: "cover", flexShrink: 0 }}
              />
            ) : (
              <span
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "50%",
                  background: "var(--accent)",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "var(--text-xs)",
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {initials}
              </span>
            )}
            <div>
              <div style={{ fontSize: "var(--text-xs)", fontWeight: 700, color: "var(--text-strong)" }}>{label}</div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>{user.email}</div>
            </div>
          </div>

          {/* AI Mode */}
          <div className="user-menu-section">
            <span className="user-menu-label">AI Mode</span>
            <div className="user-menu-mode-toggle">
              <button
                type="button"
                className={`user-menu-mode-btn${llmMode === "edge" ? " active" : ""}`}
                onClick={() => void handleModeChange("edge")}
              >
                Edge AI
              </button>
              <button
                type="button"
                className={`user-menu-mode-btn${llmMode === "cloud" ? " active" : ""}`}
                onClick={() => void handleModeChange("cloud")}
              >
                Cloud AI
              </button>
            </div>

            {llmMode === "edge" && (
              <p style={{ margin: "6px 0 0", fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
                Runs locally in your browser · no API key needed
              </p>
            )}

            {llmMode === "cloud" && (
              <div className="user-menu-cloud-fields">
                <input
                  type="password"
                  className="notes-filter-input"
                  placeholder="API Key (leave blank to keep current)"
                  value={cloudDraft.llm_api_key}
                  onChange={(e) => setCloudDraft((d) => ({ ...d, llm_api_key: e.target.value }))}
                  style={{ fontSize: "var(--text-xs)" }}
                />
                <input
                  type="text"
                  className="notes-filter-input"
                  placeholder="Base URL"
                  value={cloudDraft.llm_base_url}
                  onChange={(e) => setCloudDraft((d) => ({ ...d, llm_base_url: e.target.value }))}
                  style={{ fontSize: "var(--text-xs)" }}
                />
                <div style={{ display: "flex", gap: "6px" }}>
                  <input
                    type="text"
                    className="notes-filter-input"
                    placeholder="Model"
                    value={cloudDraft.llm_model}
                    onChange={(e) => setCloudDraft((d) => ({ ...d, llm_model: e.target.value }))}
                    style={{ flex: 1, fontSize: "var(--text-xs)" }}
                  />
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => void handleCloudSave()}
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Confidence threshold */}
          <div className="user-menu-section">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
              <span className="user-menu-label" style={{ marginBottom: 0 }}>Confidence Threshold</span>
              <span style={{ fontSize: "var(--text-xs)", fontWeight: 700, color: "var(--accent)" }}>
                {Math.round(confidenceThreshold * 100)}%
              </span>
            </div>
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.05}
              defaultValue={confidenceThreshold}
              style={{ width: "100%", accentColor: "var(--accent)" }}
              onChange={(e) => handleConfidenceChange(Number(e.target.value))}
            />
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: "2px" }}>
              <span>50%</span><span>100%</span>
            </div>
          </div>

          {/* Sign out */}
          <div>
            <button
              type="button"
              className="user-menu-signout-btn"
              onClick={() => void handleLogout()}
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd web && npm run test
```
Expected: all UserMenu tests pass.

- [ ] **Step 6: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/app/globals.css \
        web/src/components/auth/UserMenu.tsx \
        web/src/components/auth/__tests__/UserMenu.test.tsx
git commit -m "feat: rewrite UserMenu as clickable avatar dropdown with inline settings"
```

---

## Task 7: Cleanup — remove LLMSettings from NotesWorkspace + delete file

**Files:**
- Modify: `web/src/components/workspace/NotesWorkspace.tsx`
- Delete: `web/src/components/settings/LLMSettings.tsx`

- [ ] **Step 1: Remove LLMSettings state and JSX from NotesWorkspace**

In `web/src/components/workspace/NotesWorkspace.tsx`:

**a)** Remove the import:
```typescript
// DELETE this line:
import { LLMSettings } from "../settings/LLMSettings";
```

**b)** Remove the `settingsOpen` state declaration (around line 241):
```typescript
// DELETE this line:
const [settingsOpen, setSettingsOpen] = useState(false);
```

**c)** Remove the gear icon `<button>` block. It starts with:
```tsx
<button
  type="button"
  onClick={() => setSettingsOpen(true)}
  aria-label="AI settings"
```
and ends with `</button>` after the SVG path. Delete the entire button element.

**d)** Remove the `<LLMSettings>` conditional block (around line 1136–1144):
```tsx
// DELETE these lines:
{settingsOpen && (
  <LLMSettings
    prefs={prefs}
    loading={prefsLoading}
    onClose={() => setSettingsOpen(false)}
    onSaved={() => void reloadPrefs()}
  />
)}
```

**e)** Update the `<WebGPUCheck>` prop: `onOpenSettings` now becomes a direct cloud-switch call. Replace:
```tsx
onOpenSettings={() => setSettingsOpen(true)}
```
with:
```tsx
onOpenSettings={() => { void switchToCloud(); }}
```

- [ ] **Step 2: Delete LLMSettings.tsx**

```bash
rm web/src/components/settings/LLMSettings.tsx
```

- [ ] **Step 3: Run all tests**

```bash
cd web && npm run test
```
Expected: all tests pass.

- [ ] **Step 4: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/workspace/NotesWorkspace.tsx
git rm web/src/components/settings/LLMSettings.tsx
git commit -m "chore: remove LLMSettings modal (settings moved to UserMenu dropdown)"
```
