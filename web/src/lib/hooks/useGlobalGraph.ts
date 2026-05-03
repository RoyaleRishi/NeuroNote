import { useCallback, useRef, useState } from "react";
import { fetchGlobalGraph } from "../api-client";
import type { GlobalGraphResponse } from "../../../../shared/contracts/ts/v1/graph";

export interface GlobalGraphFilters {
  subject_id?: string;
  tag?: string;
}

const DEFAULT_FILTERS: GlobalGraphFilters = {};

export interface UseGlobalGraphState {
  graph: GlobalGraphResponse | null;
  isLoading: boolean;
  errorMessage: string | null;
  filters: GlobalGraphFilters;
}

export interface UseGlobalGraphActions {
  load: () => void;
  setFilters: (filters: GlobalGraphFilters) => void;
}

export function useGlobalGraph(
  baseUrl: string,
  confidenceThreshold: number = 0.9,
): UseGlobalGraphState & UseGlobalGraphActions {
  const [graph, setGraph] = useState<GlobalGraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [filters, setFilters] = useState<GlobalGraphFilters>(DEFAULT_FILTERS);
  const requestTokenRef = useRef(0);

  const load = useCallback(async () => {
    const token = requestTokenRef.current + 1;
    requestTokenRef.current = token;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const response = await fetchGlobalGraph(baseUrl, {
        min_confidence: confidenceThreshold,
        include_types: ["note", "entity"],
        subject_id: filters.subject_id,
        tag: filters.tag,
      });
      if (requestTokenRef.current !== token) return;
      setGraph(response);
    } catch {
      if (requestTokenRef.current !== token) return;
      setGraph(null);
      setErrorMessage("Failed to load global graph");
    } finally {
      if (requestTokenRef.current === token) {
        setIsLoading(false);
      }
    }
  }, [baseUrl, confidenceThreshold, filters]);

  return { graph, isLoading, errorMessage, filters, load, setFilters };
}
