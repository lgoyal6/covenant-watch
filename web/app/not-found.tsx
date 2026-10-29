import Link from "next/link";

export default function NotFound() {
  return (
    <div className="page">
      <div className="card empty">
        <h3>Page not found</h3>
        <p>
          <Link href="/companies">Back to companies</Link>
        </p>
      </div>
    </div>
  );
}
