/**
 * NLP processing job poller.
 *
 * Creates a non-blocking polling loop that calls `fetchStatus` every
 * `intervalMs` (default 1 s) and delivers each `ProcessStatusResponse` to
 * `onStatus`.  The loop stops automatically when the job reaches a terminal
 * state ("completed" | "failed") or when `stop()` is called explicitly.
 *
 * Callers own the controller lifetime — call `stop()` on component unmount
 * to prevent stale callbacks from firing after navigation.
 */
import type { ProcessStatusResponse } from "../../../../shared/contracts/ts/v1/process";

type ProcessStatus = "queued" | "running" | "completed" | "failed";

interface ProcessPollingOptions {
  fetchStatus: () => Promise<ProcessStatusResponse>;
  onStatus: (response: ProcessStatusResponse) => void;
  intervalMs?: number;
}

export interface ProcessPollingController {
  start: () => void;
  stop: () => void;
}

const TERMINAL_STATUSES: ProcessStatus[] = ["completed", "failed"];

export function createProcessPollingController(
  options: ProcessPollingOptions,
): ProcessPollingController {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let isRunning = false;

  const scheduleNext = () => {
    timer = setTimeout(() => {
      void poll();
    }, options.intervalMs ?? 1000);
  };

  const poll = async () => {
    if (!isRunning) {
      return;
    }
    try {
      const response = await options.fetchStatus();
      options.onStatus(response);

      if (!isRunning) {
        return;
      }
      if (TERMINAL_STATUSES.includes(response.status)) {
        isRunning = false;
        timer = null;
        return;
      }
      scheduleNext();
    } catch {
      isRunning = false;
      timer = null;
      options.onStatus({
        job_id: "",
        status: "failed",
        created_at: "",
        updated_at: "",
        error: "Polling failed",
      });
    }

  };

  return {
    start: () => {
      if (isRunning) {
        return;
      }
      isRunning = true;
      void poll();
    },
    stop: () => {
      isRunning = false;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    },
  };
}
