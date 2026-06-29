import Link from "next/link";

export const metadata = {
  title: "NeuroNote — Your thinking, mapped",
  description: "Write notes. Watch concepts surface and connect across everything you've written.",
};

const HERO_NODES = [
  { id: "n0", cx: 50, cy: 50, r: 9, delay: 0 },
  { id: "n1", cx: 30, cy: 28, r: 6, delay: 0.18 },
  { id: "n2", cx: 72, cy: 30, r: 6, delay: 0.35 },
  { id: "n3", cx: 22, cy: 62, r: 5, delay: 0.52 },
  { id: "n4", cx: 76, cy: 65, r: 5, delay: 0.68 },
  { id: "n5", cx: 50, cy: 15, r: 4, delay: 0.84 },
  { id: "n6", cx: 85, cy: 46, r: 4, delay: 1.0 },
  { id: "n7", cx: 14, cy: 42, r: 3.5, delay: 1.15 },
  { id: "n8", cx: 60, cy: 80, r: 3.5, delay: 1.3 },
  { id: "n9", cx: 38, cy: 82, r: 3, delay: 1.45 },
];

const HERO_EDGES = [
  { id: "e0", x1: 50, y1: 50, x2: 30, y2: 28, delay: 0.25 },
  { id: "e1", x1: 50, y1: 50, x2: 72, y2: 30, delay: 0.42 },
  { id: "e2", x1: 50, y1: 50, x2: 22, y2: 62, delay: 0.6 },
  { id: "e3", x1: 50, y1: 50, x2: 76, y2: 65, delay: 0.76 },
  { id: "e4", x1: 30, y1: 28, x2: 50, y2: 15, delay: 0.92 },
  { id: "e5", x1: 72, y1: 30, x2: 85, y2: 46, delay: 1.05 },
  { id: "e6", x1: 22, y1: 62, x2: 14, y2: 42, delay: 1.2 },
  { id: "e7", x1: 76, y1: 65, x2: 60, y2: 80, delay: 1.35 },
  { id: "e8", x1: 22, y1: 62, x2: 38, y2: 82, delay: 1.5 },
  { id: "e9", x1: 30, y1: 28, x2: 14, y2: 42, delay: 1.62 },
];

const FEATURES = [
  {
    id: "extract",
    title: "Concepts surface on their own",
    body: "Write naturally. A deterministic pipeline reads your notes and pulls out the key concepts — no prompting, no fuss.",
  },
  {
    id: "graph",
    title: "A map of how ideas connect",
    body: "Every concept links to every note that mentions it. Explore the web of your thinking in an interactive knowledge graph.",
  },
  {
    id: "ai",
    title: "AI that stays on your device",
    body: "Summaries and insights run in your browser via WebGPU. Your notes never leave your machine unless you choose cloud mode.",
  },
];

export default function LandingPage() {
  return (
    <div className="landing-shell">
      {/* ── Nav ── */}
      <nav className="landing-nav" aria-label="Site navigation">
        <span className="landing-nav-brand">NeuroNote</span>
        <Link href="/login" className="landing-nav-cta">
          Sign in
        </Link>
      </nav>

      {/* ── Hero ── */}
      <section className="landing-hero" aria-label="Hero">
        <svg
          className="landing-hero-graph"
          viewBox="0 0 100 100"
          aria-hidden="true"
          preserveAspectRatio="xMidYMid meet"
        >
          {HERO_EDGES.map((e) => (
            <line
              key={e.id}
              x1={`${e.x1}%`}
              y1={`${e.y1}%`}
              x2={`${e.x2}%`}
              y2={`${e.y2}%`}
              className="landing-hero-edge"
              style={{ animationDelay: `${e.delay}s` }}
            />
          ))}
          {HERO_NODES.map((n) => (
            <circle
              key={n.id}
              cx={`${n.cx}%`}
              cy={`${n.cy}%`}
              r={`${n.r}%`}
              className={n.id === "n0" ? "landing-hero-node landing-hero-node--root" : "landing-hero-node"}
              style={{ animationDelay: `${n.delay}s` }}
            />
          ))}
        </svg>

        <div className="landing-hero-content">
          <h1 className="landing-hero-headline">
            Your thinking,<br />mapped.
          </h1>
          <p className="landing-hero-sub">
            Write notes. Watch concepts surface and connect{" "}
            <br className="landing-br" />
            across everything you&apos;ve written.
          </p>
          <Link href="/login" className="landing-hero-btn">
            Start mapping
          </Link>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="landing-features" aria-label="Features">
        <div className="landing-features-grid">
          {FEATURES.map((f) => (
            <article key={f.id} className="landing-feature-card">
              <h2 className="landing-feature-title">{f.title}</h2>
              <p className="landing-feature-body">{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <span>NeuroNote</span>
        <Link href="/login" className="landing-footer-link">
          Sign in
        </Link>
      </footer>
    </div>
  );
}
