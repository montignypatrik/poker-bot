export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("The local study server returned an invalid response.", response.status);
  }
  if (!response.ok) throw new ApiError(payload.error || `Request failed (${response.status})`, response.status);
  return payload;
}

export const api = {
  post(path, payload) {
    return request(path, { method: "POST", body: JSON.stringify(payload) });
  },
  get(path, params = {}) {
    const query = new URLSearchParams(params);
    return request(`${path}${query.size ? `?${query}` : ""}`);
  },
};
