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
        extraction_summary: null,
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
