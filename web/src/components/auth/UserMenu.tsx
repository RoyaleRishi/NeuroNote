"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { logoutUser, updatePreferences } from "../../lib/api-client";
import { usePreferences } from "../../lib/hooks/usePreferences";
import type { UserProfile } from "../../../../shared/contracts/ts/v1/auth";

interface UserMenuProps {
  user: UserProfile | null;
}

/** Extracts up to two uppercase initials from a display name or email. */
function getInitials(displayName: string | null, email: string): string {
  const source = displayName || email.split("@")[0] || "?";
  const parts = source.trim().split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

/** Avatar circle shared between the button and the open dropdown header. */
function AvatarCircle({
  avatarUrl,
  label,
  initials,
  size,
}: {
  avatarUrl: string | null;
  label: string;
  initials: string;
  size: number;
}) {
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={label}
        style={{
          width: `${size}px`,
          height: `${size}px`,
          borderRadius: "50%",
          objectFit: "cover",
          flexShrink: 0,
        }}
      />
    );
  }
  return (
    <span
      style={{
        width: `${size}px`,
        height: `${size}px`,
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
  );
}

/**
 * Clickable avatar that opens an inline settings dropdown.
 * Handles AI mode toggling, cloud LLM config, confidence threshold, and sign-out.
 */
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

  /* Sync cloud draft from prefs when dropdown opens */
  useEffect(() => {
    if (isOpen && prefs) {
      setCloudDraft({
        llm_api_key: "",
        llm_base_url: prefs.llm_base_url,
        llm_model: prefs.llm_model,
      });
    }
  }, [isOpen, prefs]);

  /* Close on outside click */
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

  /* Close on Escape */
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  const handleModeChange = useCallback(
    async (mode: "edge" | "cloud") => {
      await updatePreferences({ llm_mode: mode });
      void reload();
    },
    [reload],
  );

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

  const handleConfidenceChange = useCallback(
    (value: number) => {
      if (confidenceTimerRef.current) clearTimeout(confidenceTimerRef.current);
      confidenceTimerRef.current = setTimeout(() => {
        void updatePreferences({ confidence_threshold: value }).then(() => reload());
      }, 500);
    },
    [reload],
  );

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
      {/* Avatar trigger button */}
      <button
        type="button"
        className="user-menu-avatar-btn"
        aria-label="Open settings"
        aria-expanded={isOpen}
        aria-haspopup="true"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <AvatarCircle avatarUrl={user.avatar_url} label={label} initials={initials} size={28} />
      </button>

      {isOpen && (
        <div className="user-menu-dropdown">
          {/* User identity */}
          <div
            className="user-menu-section"
            style={{ display: "flex", alignItems: "center", gap: "10px" }}
          >
            <AvatarCircle avatarUrl={user.avatar_url} label={label} initials={initials} size={32} />
            <div>
              <div
                style={{
                  fontSize: "var(--text-xs)",
                  fontWeight: 700,
                  color: "var(--text-strong)",
                }}
              >
                {label}
              </div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
                {user.email}
              </div>
            </div>
          </div>

          {/* AI Mode toggle */}
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
              <p
                style={{
                  margin: "6px 0 0",
                  fontSize: "var(--text-xs)",
                  color: "var(--text-muted)",
                }}
              >
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
                  onChange={(e) =>
                    setCloudDraft((d) => ({ ...d, llm_api_key: e.target.value }))
                  }
                  style={{ fontSize: "var(--text-xs)" }}
                />
                <input
                  type="text"
                  className="notes-filter-input"
                  placeholder="Base URL"
                  value={cloudDraft.llm_base_url}
                  onChange={(e) =>
                    setCloudDraft((d) => ({ ...d, llm_base_url: e.target.value }))
                  }
                  style={{ fontSize: "var(--text-xs)" }}
                />
                <div style={{ display: "flex", gap: "6px" }}>
                  <input
                    type="text"
                    className="notes-filter-input"
                    placeholder="Model"
                    value={cloudDraft.llm_model}
                    onChange={(e) =>
                      setCloudDraft((d) => ({ ...d, llm_model: e.target.value }))
                    }
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
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "6px",
              }}
            >
              <span className="user-menu-label" style={{ marginBottom: 0 }}>
                Confidence Threshold
              </span>
              <span
                style={{
                  fontSize: "var(--text-xs)",
                  fontWeight: 700,
                  color: "var(--accent)",
                }}
              >
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
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "var(--text-xs)",
                color: "var(--text-muted)",
                marginTop: "2px",
              }}
            >
              <span>50%</span>
              <span>100%</span>
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
