/** Public-facing user profile returned by `GET /v1/auth/me`. */
export interface UserProfile {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  oauth_provider: string;
  schema_name: string;
}
