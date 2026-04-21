"use client";

import React, { useState, useEffect, useCallback } from "react";
import { updatePreferences } from "../../lib/api-client";
import type { UserPreferences, UpdatePreferencesRequest } from "../../lib/api-client";

interface LLMSettingsProps {
  /** Current preferences loaded by the parent. */
  prefs: UserPreferences | null;
  /** Whether preferences are still loading. */
  loading: boolean;
  /** Close the modal without saving. */
  onClose: () => void;
  /** Called after a successful save so the parent can refresh state. */
  onSaved: () => void;
}

/**
 * Modal dialog for configuring the LLM inference mode (edge vs cloud)
 * and cloud provider settings (API key, base URL, model).
 */
export function LLMSettings({ prefs, loading, onClose, onSaved }: LLMSettingsProps) {
  const [mode, setMode] = useState<"edge" | "cloud">("edge");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* Sync local form state when prefs load or change. */
  useEffect(() => {
    if (!prefs) return;
    setMode(prefs.llm_mode);
    setApiKey(prefs.llm_api_key);
    setBaseUrl(prefs.llm_base_url);
    setModel(prefs.llm_model);
  }, [prefs]);

  /* Close on Escape key. */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const payload: UpdatePreferencesRequest = { llm_mode: mode };
      if (mode === "cloud") {
        payload.llm_api_key = apiKey;
        payload.llm_base_url = baseUrl;
        payload.llm_model = model;
      }
      await updatePreferences(payload);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save preferences");
    } finally {
      setSaving(false);
    }
  }, [mode, apiKey, baseUrl, model, onSaved, onClose]);

  /* Prevent clicks inside the card from closing the modal. */
  const stopPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="LLM Settings"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: "var(--z-modal, 1000)" as unknown as number,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0, 0, 0, 0.45)",
      }}
    >
      <div
        onClick={stopPropagation}
        style={{
          background: "var(--panel-bg)",
          border: "1px solid var(--panel-border)",
          borderRadius: "12px",
          padding: "2rem 1.75rem",
          width: "100%",
          maxWidth: "420px",
          boxShadow: "var(--shadow-panel)",
        }}
      >
        {/* Header */}
        <h2
          style={{
            margin: "0 0 0.25rem",
            fontSize: "1.125rem",
            fontWeight: 700,
            color: "var(--text-strong)",
            letterSpacing: "-0.01em",
          }}
        >
          AI Settings
        </h2>
        <p style={{ margin: "0 0 1.25rem", fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
          Choose how NeuroNote runs AI inference.
        </p>

        {loading ? (
          <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>Loading...</p>
        ) : (
          <>
            {/* Mode toggle */}
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.25rem" }}>
              <ModeButton
                label="Edge AI (In-Browser)"
                active={mode === "edge"}
                onClick={() => setMode("edge")}
              />
              <ModeButton
                label="Cloud AI (API Key)"
                active={mode === "cloud"}
                onClick={() => setMode("cloud")}
              />
            </div>

            {mode === "edge" ? (
              <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)", margin: "0 0 1.25rem", lineHeight: 1.5 }}>
                AI runs locally in your browser using WebGPU. No API key needed.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "1.25rem" }}>
                <SettingsField label="API Key">
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-..."
                    autoComplete="off"
                    style={inputStyle}
                  />
                </SettingsField>
                <SettingsField label="Base URL">
                  <input
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://api.openai.com/v1"
                    style={inputStyle}
                  />
                </SettingsField>
                <SettingsField label="Model">
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="gpt-4o-mini"
                    style={inputStyle}
                  />
                </SettingsField>
              </div>
            )}

            {/* Error message */}
            {error && (
              <p style={{ fontSize: "var(--text-xs)", color: "var(--danger)", margin: "0 0 0.75rem" }}>
                {error}
              </p>
            )}

            {/* Action buttons */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
              <button type="button" onClick={onClose} style={cancelButtonStyle}>
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                style={{
                  ...saveButtonStyle,
                  opacity: saving ? 0.6 : 1,
                  cursor: saving ? "not-allowed" : "pointer",
                }}
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────────────────── */

/** Radio-style toggle button for mode selection. */
function ModeButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 1,
        padding: "0.5rem 0.75rem",
        fontSize: "var(--text-sm)",
        fontWeight: active ? 600 : 400,
        color: active ? "var(--accent)" : "var(--text-muted)",
        background: active ? "var(--accent-soft)" : "transparent",
        border: `1px solid ${active ? "var(--accent)" : "var(--panel-border)"}`,
        borderRadius: "6px",
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      {label}
    </button>
  );
}

/** Labelled wrapper for a form field. */
function SettingsField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
      <span style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-strong)" }}>
        {label}
      </span>
      {children}
    </label>
  );
}

/* ── Shared inline styles ────────────────────────────────────────────── */

const inputStyle: React.CSSProperties = {
  padding: "0.5rem 0.625rem",
  fontSize: "var(--text-sm)",
  color: "var(--text-strong)",
  background: "var(--workspace-bg)",
  border: "1px solid var(--input-border)",
  borderRadius: "6px",
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const cancelButtonStyle: React.CSSProperties = {
  padding: "0.4rem 0.875rem",
  fontSize: "var(--text-sm)",
  fontWeight: 600,
  color: "var(--text-muted)",
  background: "transparent",
  border: "1px solid var(--panel-border)",
  borderRadius: "6px",
  cursor: "pointer",
};

const saveButtonStyle: React.CSSProperties = {
  padding: "0.4rem 0.875rem",
  fontSize: "var(--text-sm)",
  fontWeight: 600,
  color: "#fff",
  background: "var(--accent)",
  border: "1px solid var(--accent)",
  borderRadius: "6px",
  cursor: "pointer",
};
