import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  CONSENT_KEY,
  PENDING_KEY,
  STALE_PENDING_MS,
  readConsent,
  writeConsent,
  clearConsent,
  readPendingFlag,
  writePendingFlag,
  clearPendingFlag,
} from "../persistence";

describe("edge-llm/persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  describe("consent", () => {
    it("returns null when nothing is stored", () => {
      expect(readConsent()).toBeNull();
    });

    it("round-trips 'accepted'", () => {
      writeConsent("accepted");
      expect(readConsent()).toBe("accepted");
      expect(window.localStorage.getItem(CONSENT_KEY)).toBe("accepted");
    });

    it("round-trips 'declined'", () => {
      writeConsent("declined");
      expect(readConsent()).toBe("declined");
    });

    it("returns null for unknown stored values", () => {
      window.localStorage.setItem(CONSENT_KEY, "garbage");
      expect(readConsent()).toBeNull();
    });

    it("clearConsent removes the entry", () => {
      writeConsent("accepted");
      clearConsent();
      expect(readConsent()).toBeNull();
    });
  });

  describe("pending flag", () => {
    it("returns null when nothing is stored", () => {
      expect(readPendingFlag()).toBeNull();
    });

    it("round-trips an object", () => {
      writePendingFlag(123456);
      const got = readPendingFlag();
      expect(got).toEqual({ startedAt: 123456 });
    });

    it("returns null for malformed JSON", () => {
      window.localStorage.setItem(PENDING_KEY, "{not json");
      expect(readPendingFlag()).toBeNull();
    });

    it("returns null when startedAt is not a number", () => {
      window.localStorage.setItem(
        PENDING_KEY,
        JSON.stringify({ startedAt: "yesterday" }),
      );
      expect(readPendingFlag()).toBeNull();
    });

    it("clearPendingFlag removes the entry", () => {
      writePendingFlag(Date.now());
      clearPendingFlag();
      expect(readPendingFlag()).toBeNull();
    });
  });

  describe("STALE_PENDING_MS", () => {
    it("equals one hour", () => {
      expect(STALE_PENDING_MS).toBe(60 * 60 * 1000);
    });
  });

  describe("localStorage unavailable", () => {
    it("read functions return null when localStorage throws", () => {
      // Spy on the storage object directly (own-property methods from setup.ts).
      const spy = vi
        .spyOn(window.localStorage, "getItem")
        .mockImplementation(() => {
          throw new Error("private mode");
        });
      expect(readConsent()).toBeNull();
      expect(readPendingFlag()).toBeNull();
      spy.mockRestore();
    });

    it("write functions swallow errors", () => {
      // Spy on the storage object directly (own-property methods from setup.ts).
      const spy = vi
        .spyOn(window.localStorage, "setItem")
        .mockImplementation(() => {
          throw new Error("quota exceeded");
        });
      expect(() => writeConsent("accepted")).not.toThrow();
      expect(() => writePendingFlag(1)).not.toThrow();
      spy.mockRestore();
    });
  });
});
