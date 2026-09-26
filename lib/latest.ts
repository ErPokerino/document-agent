/**
 * Only the answer to the most recent request may reach the screen.
 *
 * Two fetches for the same slot of state can resolve in either order. The Lab
 * poll asked for the running evaluation every two seconds; one still in flight
 * when a different run was opened restored the running one over it.
 */
export type Latest = {
  /** Start a request; the returned check stays true until a newer one starts. */
  begin(): () => boolean;
  /** Discard whatever is in flight, for a slot that was just cleared. */
  invalidate(): void;
};

export function latestOnly(): Latest {
  let current = 0;
  return {
    begin() {
      const ticket = ++current;
      return () => ticket === current;
    },
    invalidate() {
      current += 1;
    },
  };
}
