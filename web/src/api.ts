// Calls to the local server. Anything that changes data carries the header the server requires.

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

const listeners = new Set<() => void>();

/** Called when the server says the session has ended (idle too long, or the app was restarted). */
export function onSignedOut(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function request<T>(method: string, path: string, body?: unknown, raw?: Blob): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-Requested-With"] = "searchables";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method,
    headers,
    body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
    credentials: "same-origin",
  });
  if (!response.ok) {
    let message = `The server answered ${response.status}.`;
    try {
      message = (await response.json()).error ?? message;
    } catch { /* Not JSON: keep the status */ }
    if (response.status === 401 && !path.startsWith("/session")) listeners.forEach((listener) => listener());
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T,>(path: string, body: unknown = {}) => request<T>("PUT", path, body),
  patch: <T,>(path: string, body: unknown = {}) => request<T>("PATCH", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path, {}),
  upload: <T,>(path: string, file: Blob) => request<T>("POST", path, undefined, file),
};

/** Query string from the values that are set: lists are joined with commas, as the server expects. */
export function query(params: Record<string, string | number | boolean | string[] | number[] | undefined | null>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    if (Array.isArray(value)) {
      if (value.length) parts.push(`${key}=${encodeURIComponent(value.join(","))}`);
    } else {
      parts.push(`${key}=${encodeURIComponent(value === true ? "1" : String(value))}`);
    }
  }
  return parts.length ? "?" + parts.join("&") : "";
}
