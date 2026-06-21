import { LoadingGraph } from "../components/ui/LoadingGraph";

export default function Loading() {
  return (
    <div className="app-loading-screen" aria-label="Loading NeuroNote">
      <LoadingGraph />
    </div>
  );
}
