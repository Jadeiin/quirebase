// Shared CSRF contract: the session-bound synchronizer token is rendered once as
// <meta name="csrf-token"> by base.html and attached as a header to same-origin
// mutations. Native forms carry it as the csrf_token hidden field instead
// (templates/_forms.html); never read the token from a URL or localStorage.
let token;

export function csrfToken() {
  if (token === undefined) {
    token = document.querySelector('meta[name="csrf-token"]')?.content ?? "";
  }
  return token;
}

export function csrfFetch(url, options = {}) {
  const headers = { "X-CSRF-Token": csrfToken(), ...(options.headers || {}) };
  return fetch(url, { ...options, headers });
}
