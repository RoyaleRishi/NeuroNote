/** All user preferences as a flat object. */
export interface UserPreferences {
  llm_mode: "edge" | "cloud";
  llm_api_key: string;
  llm_base_url: string;
  llm_model: string;
}

/** Partial update — only provided fields are written. */
export interface UpdatePreferencesRequest {
  llm_mode?: "edge" | "cloud";
  llm_api_key?: string;
  llm_base_url?: string;
  llm_model?: string;
}
