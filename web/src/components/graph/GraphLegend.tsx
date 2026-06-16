"use client";

import { EDGE_GROUPS, EDGE_GROUP_CSS_VAR, getEdgeStyle } from "./graph-styling";

interface GraphLegendProps {
  /** Edge types actually present in the current graph (drives which rows show). */
  presentTypes: string[];
  hidden: Set<string>;
  highlighted: Set<string>;
  onToggleHidden: (type: string) => void;
  onToggleHighlighted: (type: string) => void;
}

/** A tiny SVG preview of an edge's form (width + dash + arrow), coloured by group. */
function EdgeSwatch({ type }: { type: string }) {
  const style = getEdgeStyle(type);
  const stroke = `var(${EDGE_GROUP_CSS_VAR[style.group]})`;
  const markerId = `legend-arrow-${type}`;
  return (
    <svg className="graph-legend-swatch" width="34" height="12" viewBox="0 0 34 12" aria-hidden="true">
      {style.directed && (
        <defs>
          <marker
            id={markerId}
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
            markerUnits="userSpaceOnUse"
          >
            <path d="M0,0 L6,3 L0,6 Z" fill={stroke} />
          </marker>
        </defs>
      )}
      <line
        x1="1"
        y1="6"
        x2={style.directed ? 26 : 33}
        y2="6"
        stroke={stroke}
        strokeWidth={style.width}
        strokeDasharray={style.dash || undefined}
        markerEnd={style.directed ? `url(#${markerId})` : undefined}
      />
    </svg>
  );
}

export function GraphLegend({
  presentTypes,
  hidden,
  highlighted,
  onToggleHidden,
  onToggleHighlighted,
}: GraphLegendProps) {
  const present = new Set(presentTypes);
  const groups = EDGE_GROUPS.map((g) => ({
    ...g,
    types: g.types.filter((t) => present.has(t)),
  })).filter((g) => g.types.length > 0);

  if (groups.length === 0) return null;

  return (
    <section className="graph-legend" aria-label="Relationship types">
      <p className="graph-legend-key">
        <span className="graph-legend-key-item">
          <span aria-hidden="true">☑</span> show
        </span>
        <span className="graph-legend-key-item">
          <span aria-hidden="true" className="graph-legend-key-dot">◉</span> highlight
        </span>
      </p>
      {groups.map((group) => (
        <div className="graph-legend-group" key={group.id}>
          <p className="graph-legend-group-label">{group.label}</p>
          {group.types.map((type) => {
            const style = getEdgeStyle(type);
            const isHidden = hidden.has(type);
            const isHighlighted = highlighted.has(type);
            return (
              <div className="graph-legend-row" key={type}>
                <label className="graph-legend-toggle">
                  <input
                    type="checkbox"
                    checked={!isHidden}
                    onChange={() => onToggleHidden(type)}
                    aria-label={`Show ${style.label}`}
                  />
                  <EdgeSwatch type={type} />
                  <span className="graph-legend-name">{style.label}</span>
                </label>
                <button
                  type="button"
                  className="graph-legend-highlight"
                  title={`Highlight ${style.label}`}
                  aria-label={`Highlight ${style.label}`}
                  aria-pressed={isHighlighted}
                  onClick={() => onToggleHighlighted(type)}
                  onKeyDown={(e) => {
                    // jsdom (and a11y correctness) — activate on Space/Enter explicitly,
                    // preventing the synthesised click so we don't double-toggle.
                    if (e.key === " " || e.key === "Enter") {
                      e.preventDefault();
                      onToggleHighlighted(type);
                    }
                  }}
                >
                  <span aria-hidden="true">{isHighlighted ? "◉" : "○"}</span>
                </button>
              </div>
            );
          })}
        </div>
      ))}
    </section>
  );
}
