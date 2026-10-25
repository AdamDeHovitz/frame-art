// Only requests made by this app receive the header required for LAN TV changes.
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin === location.origin && method === 'POST') {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-Stillroom-Request', '1');
      init = {...init, headers};
    }
    return originalFetch(input, init);
  };
})();
