"use client";

export default function WorkspaceError({ reset }: { reset: () => void }) {
  return (
    <main className="workspace__main">
      <p className="eyebrow">Private workspace</p>
      <h1>We could not load this page.</h1>
      <p>Your data has not changed. Try loading it again.</p>
      <button className="button button--primary" type="button" onClick={reset}>
        Try again
      </button>
    </main>
  );
}
