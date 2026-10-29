export default function Loading() {
  return (
    <div className="page stack">
      <div className="skeleton" style={{ height: 28, width: 320 }} />
      <div className="skeleton" style={{ height: 140 }} />
      <div className="skeleton" style={{ height: 360 }} />
    </div>
  );
}
