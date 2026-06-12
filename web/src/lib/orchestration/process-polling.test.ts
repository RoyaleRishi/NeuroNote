import { beforeEach, describe, expect, it, vi } from "vitest";

import { createProcessPollingController } from "./process-polling";
import type { ProcessStatusResponse } from "../../../../shared/contracts/ts/v1/process";

function makeResponse(overrides: Partial<ProcessStatusResponse> = {}): ProcessStatusResponse {
  return {
    job_id: "job-1",
    status: "running",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    error: null,
    extraction_summary: null,
    ...overrides,
  };
}

describe("createProcessPollingController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("polls until it receives a terminal status", async () => {
    const fetchStatus = vi
      .fn()
      .mockResolvedValueOnce(makeResponse({ status: "running" }))
      .mockResolvedValueOnce(makeResponse({ status: "completed" }));
    const onStatus = vi.fn();

    const controller = createProcessPollingController({
      fetchStatus,
      onStatus,
      intervalMs: 500,
    });

    controller.start();
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();

    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({ status: "running" }));
    expect(onStatus).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  });

  it("stops polling when requested", async () => {
    const fetchStatus = vi.fn().mockResolvedValue(makeResponse({ status: "running" }));
    const onStatus = vi.fn();
    const controller = createProcessPollingController({
      fetchStatus,
      onStatus,
      intervalMs: 500,
    });

    controller.start();
    await Promise.resolve();
    controller.stop();
    await vi.advanceTimersByTimeAsync(2000);

    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("passes extraction_summary when completed", async () => {
    const summary = { entity_count: 3, relation_count: 1, top_entities: ["foo"] };
    const fetchStatus = vi.fn().mockResolvedValueOnce(
      makeResponse({ status: "completed", extraction_summary: summary }),
    );
    const onStatus = vi.fn();

    const controller = createProcessPollingController({
      fetchStatus,
      onStatus,
      intervalMs: 500,
    });

    controller.start();
    await vi.runOnlyPendingTimersAsync();

    expect(onStatus).toHaveBeenCalledWith(
      expect.objectContaining({ status: "completed", extraction_summary: summary }),
    );
  });
});
