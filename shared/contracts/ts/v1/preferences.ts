/** All user preferences as a flat object. */
export interface UserPreferences {
  llm_mode: "edge" | "cloud";
  llm_api_key: string;
  llm_base_url: string;
  llm_model: string;
  confidence_threshold: number;
  /** True when PREF_ENCRYPTION_KEY is set but the stored key can't be decrypted
   * (e.g. after key rotation). UI should prompt the user to re-enter their key. */
  llm_api_key_invalid: boolean;
}

/** Partial update — only provided fields are written. */
export interface UpdatePreferencesRequest {
  llm_mode?: "edge" | "cloud";
  llm_api_key?: string;
  llm_base_url?: string;
  llm_model?: string;
  confidence_threshold?: number;
}

/** Result of a test LLM connection attempt. */
export interface TestConnectionResponse {
  success: boolean;
  message: string;
}
