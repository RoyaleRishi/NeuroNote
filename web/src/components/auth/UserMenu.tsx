"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { logoutUser, testLlmConnection } from "../../lib/api-client";
import { useDismissable } from "../../lib/hooks/useDismissable";
import { usePreferences } from "../../lib/hooks/usePreferences";
import { useOptionalToast } from "../../lib/toast";
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
        color: "var(--text-on-accent)",
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
  const { prefs, mutate } = usePreferences();
  const { showToast } = useOptionalToast();
  const [isOpen, setIsOpen] = useState(false);
  const [cloudDraft, setCloudDraft] = useState({
    llm_api_key: "",
    llm_base_url: "https://api.openai.com/v1",
    llm_model: "gpt-4o-mini",
  });
  const [saving, setSaving] = useState(false);
  // Result of the post-save test-connection call.  Surfaced inline so users
  // can see why their model/key combination is rejected before they hit
  // the concept-insight panel.
  const [testStatus, setTestStatus] = useState<
    { ok: boolean; message: string } | null
  >(null);
  // Optimistic slider values: driven by local state so they never snap back to
  // the persisted value during the debounce + round-trip. Two decoupled graph
  // filters — concept relevance (node salience) and relationship strength.
  const [localNodeSalience, setLocalNodeSalience] = useState(0.5);
  const [localRelConfidence, setLocalRelConfidence] = useState(0.5);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const thresholdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* Keep the optimistic sliders in sync with persisted prefs */
  useEffect(() => {
    if (prefs) {
      setLocalNodeSalience(prefs.node_salience_threshold);
      setLocalRelConfidence(prefs.relationship_confidence_threshold);
    }
  }, [prefs]);

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

  useDismissable(wrapperRef, isOpen, () => setIsOpen(false));

  const handleModeChange = useCallback(
    async (mode: "edge" | "cloud") => {
      try {
        await mutate({ llm_mode: mode });
        showToast(`Summaries: ${mode === "edge" ? "on-device" : "cloud"}`, "success");
      } catch (err) {
        showToast(err instanceof Error ? err.message : "Could not update AI mode.", "error");
      }
    },
    [mutate, showToast],
  );

  const handleCloudSave = useCallback(async () => {
    setSaving(true);
    setTestStatus(null);
    try {
      await mutate({
        llm_api_key: cloudDraft.llm_api_key || undefined,
        llm_base_url: cloudDraft.llm_base_url,
        llm_model: cloudDraft.llm_model,
      });
      showToast("Cloud summary settings saved", "success");
      // Validate the just-saved config end-to-end.  We save first because
      // /v1/preferences/test-connection reads from the persisted prefs;
      // if validation fails the user keeps the bad config but is told why,
      // so they can fix the model/key/base-url.
      try {
        const result = await testLlmConnection();
        setTestStatus({ ok: result.success, message: result.message });
      } catch (exc) {
        setTestStatus({
          ok: false,
          message: exc instanceof Error ? exc.message : "Could not validate connection.",
        });
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Could not save settings.", "error");
    } finally {
      setSaving(false);
    }
  }, [cloudDraft, mutate, showToast]);

  const handleThresholdChange = useCallback(
    (
      key: "node_salience_threshold" | "relationship_confidence_threshold",
      value: number,
      setLocal: (v: number) => void,
    ) => {
      setLocal(value); // optimistic — hold the dragged position
      if (thresholdTimerRef.current) clearTimeout(thresholdTimerRef.current);
      thresholdTimerRef.current = setTimeout(() => {
        void mutate({ [key]: value })
          .then(() => showToast("Graph filter updated", "success"))
          .catch((err: unknown) => {
            showToast(
              err instanceof Error ? err.message : "Could not save filter.",
              "error",
            );
            // Revert the optimistic value to the last persisted one.
            if (prefs) {
              setLocalNodeSalience(prefs.node_salience_threshold);
              setLocalRelConfidence(prefs.relationship_confidence_threshold);
            }
          });
      }, 500);
    },
    [mutate, showToast, prefs],
  );

  const handleLogout = useCallback(async () => {
    await logoutUser();
    window.location.href = "/login";
  }, []);

  if (!user) return null;

  const initials = getInitials(user.display_name, user.email);
  const label = user.display_name || user.email;
  const llmMode = prefs?.llm_mode ?? "edge";

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
          <div className="user-menu-section user-menu-identity">
            <AvatarCircle avatarUrl={user.avatar_url} label={label} initials={initials} size={32} />
            <div>
              <div className="user-menu-identity-name">{label}</div>
              <div className="user-menu-identity-email">{user.email}</div>
            </div>
          </div>

          {/* Summaries & insights engine — this only controls the generative
              LLM used for note summaries and concept insights. Concept
              extraction + the knowledge graph always run on the server. */}
          <div className="user-menu-section">
            <span className="user-menu-label">Summaries &amp; Insights</span>
            <div className="user-menu-mode-toggle">
              <button
                type="button"
                className={`user-menu-mode-btn${llmMode === "edge" ? " active" : ""}`}
                onClick={() => void handleModeChange("edge")}
                aria-pressed={llmMode === "edge"}
              >
                On-device
              </button>
              <button
                type="button"
                className={`user-menu-mode-btn${llmMode === "cloud" ? " active" : ""}`}
                onClick={() => void handleModeChange("cloud")}
                aria-pressed={llmMode === "cloud"}
              >
                Cloud
              </button>
            </div>

            {llmMode === "edge" && (
              <p className="user-menu-mode-hint">
                Written in your browser (Gemma) · not sent to any AI provider
              </p>
            )}

            <p className="user-menu-mode-note">
              Your concepts &amp; knowledge graph are always built on your
              NeuroNote server — no setup, in either mode.
            </p>

            {llmMode === "cloud" && (
              <div className="user-menu-cloud-fields">
                <input
                  type="password"
                  className="notes-filter-input user-menu-cloud-input"
                  placeholder="API Key (leave blank to keep current)"
                  value={cloudDraft.llm_api_key}
                  onChange={(e) =>
                    setCloudDraft((d) => ({ ...d, llm_api_key: e.target.value }))
                  }
                  aria-label="API Key"
                />
                <input
                  type="text"
                  className="notes-filter-input user-menu-cloud-input"
                  placeholder="Base URL"
                  value={cloudDraft.llm_base_url}
                  onChange={(e) =>
                    setCloudDraft((d) => ({ ...d, llm_base_url: e.target.value }))
                  }
                  aria-label="Base URL"
                />
                <div className="user-menu-cloud-input-row">
                  <input
                    type="text"
                    className="notes-filter-input user-menu-cloud-input"
                    placeholder="Model"
                    value={cloudDraft.llm_model}
                    onChange={(e) =>
                      setCloudDraft((d) => ({ ...d, llm_model: e.target.value }))
                    }
                    aria-label="Model"
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
                {testStatus && (
                  <p
                    role={testStatus.ok ? "status" : "alert"}
                    className={`user-menu-test-status${testStatus.ok ? "" : " error"}`}
                  >
                    {testStatus.message}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Graph filters — two decoupled thresholds */}
          <div className="user-menu-section">
            {/* Concept relevance (node salience) */}
            <div className="user-menu-confidence-row">
              <span className="user-menu-label">Concept relevance</span>
              <span className="user-menu-confidence-value">
                {Math.round(localNodeSalience * 100)}%
              </span>
            </div>
            <input
              type="range"
              className="user-menu-confidence-slider"
              min={0}
              max={1}
              step={0.05}
              value={localNodeSalience}
              onChange={(e) =>
                handleThresholdChange(
                  "node_salience_threshold",
                  Number(e.target.value),
                  setLocalNodeSalience,
                )
              }
              aria-label="Concept relevance threshold"
            />
            <div className="user-menu-confidence-bounds">
              <span>Show all</span>
              <span>Most relevant</span>
            </div>

            {/* Relationship strength (edge confidence) */}
            <div className="user-menu-confidence-row">
              <span className="user-menu-label">Relationship strength</span>
              <span className="user-menu-confidence-value">
                {Math.round(localRelConfidence * 100)}%
              </span>
            </div>
            <input
              type="range"
              className="user-menu-confidence-slider"
              min={0}
              max={1}
              step={0.05}
              value={localRelConfidence}
              onChange={(e) =>
                handleThresholdChange(
                  "relationship_confidence_threshold",
                  Number(e.target.value),
                  setLocalRelConfidence,
                )
              }
              aria-label="Relationship strength threshold"
            />
            <div className="user-menu-confidence-bounds">
              <span>All links</span>
              <span>Strongest</span>
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
