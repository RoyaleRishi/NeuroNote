import { OAuthButtons } from "../../components/auth/OAuthButtons";

export default function LoginPage() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--workspace-bg)" }}>
      <div style={{ background: "var(--panel-bg)", border: "1px solid var(--panel-border)", borderRadius: "12px", padding: "2.5rem 2rem", width: "100%", maxWidth: "360px", boxShadow: "var(--shadow-panel)" }}>
        <h1 style={{ margin: "0 0 0.25rem", fontSize: "1.25rem", fontWeight: 700, color: "var(--text-strong)", letterSpacing: "-0.01em" }}>
          NeuroNote
        </h1>
        <p style={{ margin: "0 0 1.75rem", fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
          Sign in to your workspace
        </p>
        <OAuthButtons />
      </div>
    </div>
  );
}
