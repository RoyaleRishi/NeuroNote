export default function Loading() {
  return (
    <div className="app-loading-screen" aria-label="Loading NeuroNote">
      <div className="app-loading-inner">
        <span className="app-loading-brand">NeuroNote</span>
        <div className="app-loading-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}
