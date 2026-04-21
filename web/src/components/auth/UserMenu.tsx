"use client";

import { useCallback } from "react";
import { logoutUser } from "../../lib/api-client";
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

/** Displays the authenticated user's avatar, name, and a sign-out action. */
export function UserMenu({ user }: UserMenuProps) {
  const handleLogout = useCallback(async () => {
    await logoutUser();
    window.location.href = "/login";
  }, []);

  if (!user) return null;

  const initials = getInitials(user.display_name, user.email);
  const label = user.display_name || user.email;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      {user.avatar_url ? (
        <img
          src={user.avatar_url}
          alt={label}
          style={{
            width: "28px",
            height: "28px",
            borderRadius: "50%",
            objectFit: "cover",
          }}
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
      <span
        style={{
          fontSize: "var(--text-sm)",
          color: "var(--text-strong)",
          maxWidth: "120px",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <button
        type="button"
        onClick={() => void handleLogout()}
        style={{
          marginLeft: "0.25rem",
          padding: "0.25rem 0.5rem",
          fontSize: "var(--text-xs)",
          fontWeight: 600,
          color: "var(--text-muted)",
          background: "transparent",
          border: "1px solid var(--panel-border)",
          borderRadius: "4px",
          cursor: "pointer",
          transition: "color 0.15s",
        }}
      >
        Sign out
      </button>
    </div>
  );
}
