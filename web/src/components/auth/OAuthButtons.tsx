"use client";

import { getBaseUrl } from "../../lib/api-client";

/** Full-width OAuth login buttons for Google and GitHub. */
export function OAuthButtons() {
  const apiBase = getBaseUrl();

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
