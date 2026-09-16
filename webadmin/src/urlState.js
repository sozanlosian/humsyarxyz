export function readHashQuery() {
  const raw = window.location.hash.replace(/^#/, '');
  return new URLSearchParams(raw.includes('?') ? raw.split('?').slice(1).join('?') : '');
}

export function writeHashQuery(path, values) {
  const params = new URLSearchParams();
  Object.entries(values || {}).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined && value !== false) params.set(key, String(value));
  });
  const next = `#${path}${params.toString() ? `?${params}` : ''}`;
  if (window.location.hash !== next) window.history.replaceState(null, '', next);
}

export const queryNumber = (params, key, fallback) => {
  const value = Number(params.get(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};
