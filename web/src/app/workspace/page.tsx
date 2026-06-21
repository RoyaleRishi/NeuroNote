import { NotesWorkspace } from "../../components/workspace/NotesWorkspace";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export default function WorkspacePage() {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
  return <NotesWorkspace baseUrl={baseUrl} />;
}
