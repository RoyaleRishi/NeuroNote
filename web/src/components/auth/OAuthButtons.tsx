"use client";

import { useEffect, useState } from "react";
import { getBaseUrl } from "../../lib/api-client";

/** Full-width OAuth login buttons for Google and GitHub, with dev mode fallback. */
export function OAuthButtons() {
  const apiBase = getBaseUrl();
  const [devMode, setDevMode] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${apiBase}/v1/auth/dev/status`, { credentials: "include" })
      .then((r) => r.json())
      .then((data) => setDevMode(data.dev_mode === true))
      .catch(() => setDevMode(false));
  }, [apiBase]);

  async function handleDevLogin() {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/v1/auth/dev/login`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        window.location.href = "/";
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  const buttonStyle: React.CSSProperties = {
    display: "block",
    width: "100%",
    boxSizing: "border-box",
    padding: "0.6rem 1rem",
    fontSize: "var(--text-base)",
    fontWeight: 600,
    textAlign: "center",
    textDecoration: "none",
    borderRadius: "6px",
    border: "1px solid var(--panel-border)",
    background: "var(--panel-bg)",
    color: "var(--text-strong)",
    cursor: "pointer",
    transition: "background 0.15s, border-color 0.15s",
  };

  const accentButtonStyle: React.CSSProperties = {
    ...buttonStyle,
    background: "var(--accent)",
    color: "#fff",
    border: "1px solid var(--accent)",
  };

  if (devMode === null) return null; // loading state check

  if (devMode) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <button type="button" onClick={() => void handleDevLogin()} disabled={loading} style={accentButtonStyle}>
          {loading ? "Signing in..." : "Sign in as Dev User"}
        </button>
        <p style={{ margin: 0, fontSize: "var(--text-xs)", color: "var(--text-muted)", textAlign: "center" }}>
          Dev mode — no OAuth providers configured
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <a href={`${apiBase}/v1/auth/google/login`} style={accentButtonStyle}>
        Sign in with Google
      </a>
      <a href={`${apiBase}/v1/auth/github/login`} style={buttonStyle}>
        Sign in with GitHub
      </a>
    </div>
  );
}
