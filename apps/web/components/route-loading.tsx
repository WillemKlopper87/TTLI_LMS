/**
 * Route-level loading fallback (F18, BACKLOG.md). Next renders a
 * `loading.tsx` while a server-rendered route waits on its API reads, so a
 * storefront navigation shows this instead of the previous page or a blank.
 *
 * Deliberately plain: a labelled, polite live region plus a quiet bar. The
 * label is real text (not only a visual shimmer) so a screen-reader user
 * hears that something is loading.
 */
export function RouteLoading({ label = "Loading" }: { label?: string }) {
  return (
    <main className="route-loading">
      <div role="status" aria-live="polite">
        <span className="route-loading__label">{label}…</span>
        <div className="route-loading__bar" aria-hidden="true" />
      </div>
    </main>
  );
}
