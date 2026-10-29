"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="page">
      <div className="error-box stack" style={{ gap: 8 }} role="alert">
        <h3>Something went wrong rendering this page</h3>
        <p className="small text-2">{error.message || "Unexpected error."}</p>
        <div>
          <button className="btn btn-sm" type="button" onClick={reset}>
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}
