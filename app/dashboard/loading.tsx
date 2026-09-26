export default function WorkspaceLoading() {
  return (
    <main className="workspace__main" role="status" aria-live="polite">
      <p className="eyebrow">Private workspace</p>
      <h1>Loading your workspace…</h1>
      <p>Retrieving your documents and analysis.</p>
    </main>
  );
}
