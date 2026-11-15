// Retry only reads and mutations protected by booking idempotency.
window.treamFetch = async function (url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const path = new URL(url, location.href).pathname;
  const safe =
    method === "GET" ||
    (method === "POST" &&
      (path === "/bookings" ||
        /^\/bookings\/[^/]+\/(change|cancel)$/.test(path)));
  const attempts = safe ? 5 : 1;
  for (let attempt = 0; attempt < attempts; attempt++) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (options.signal?.aborted || attempt === attempts - 1) throw error;
    }
    if (
      response &&
      (![429, 502, 503, 504].includes(response.status) ||
        attempt === attempts - 1)
    )
      return response;
    const retryAfter = response?.headers.get("Retry-After");
    const seconds =
      retryAfter && /^\d+(\.\d+)?$/.test(retryAfter) ? Number(retryAfter) : 0;
    const delay = Math.min(
      10000,
      Math.max(
        seconds * 1000,
        (0.5 + Math.random()) * Math.min(4000, 400 * 2 ** attempt),
      ),
    );
    if (response?.body) await response.body.cancel().catch(() => {});
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
};
