/**
 * Note save/process lifecycle controller.
 *
 * Wraps two debounced actions — autosave and processing queue — behind a
 * simple `onEdit` / `onBlur` / `dispose` interface so editor components
 * don't need to own timer state.
 *
 * Defaults: autosave 800 ms, process queue 3 000 ms.  `onBlur` flushes
 * both timers immediately (e.g. tab close / navigation away).
 */
import { createDebouncedAction } from "../timing/debounce";

interface NoteLifecycleOptions {
  onAutosave: () => void | Promise<void>;
  onQueueProcessing: () => void | Promise<void>;
  autosaveDebounceMs?: number;
  processDebounceMs?: number;
}

export interface NoteLifecycleController {
  onEdit: () => void;
  onBlur: () => void;
  dispose: () => void;
}

export function createNoteLifecycleController(
  options: NoteLifecycleOptions,
): NoteLifecycleController {
  const autosave = createDebouncedAction(
    () => void options.onAutosave(),
    options.autosaveDebounceMs ?? 800,
  );
  const processQueue = createDebouncedAction(
    () => void options.onQueueProcessing(),
    options.processDebounceMs ?? 3000,
  );

  return {
    onEdit: () => {
      autosave.call();
      processQueue.call();
    },
    onBlur: () => {
      autosave.flush();
      processQueue.flush();
    },
    dispose: () => {
      autosave.cancel();
      processQueue.cancel();
    },
  };
}
