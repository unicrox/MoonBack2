export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8200";

const CONST_HASH_STORAGE_KEY = "moonback.frontend_consts_hash";
const CONSTS_STORAGE_KEY = "moonback.frontend_consts";

type FrontendConsts = Record<string, unknown>;

type ResponseMeta = {
  const_hash?: string | null;
  consts?: FrontendConsts | null;
};

export type ApiResponse<T = unknown> = {
  code: number;
  message?: string | null;
  data?: T | null;
  meta?: ResponseMeta | null;
};

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | Record<string, unknown> | null;
};

export class ApiError extends Error {
  status: number;
  code?: number;
  data?: unknown;

  constructor(message: string, status: number, code?: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

function buildApiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }

  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function readStorageValue(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorageValue(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable in private mode or restricted webviews.
  }
}

export function getFrontendConstsHash(): string | null {
  return readStorageValue(CONST_HASH_STORAGE_KEY);
}

export function getFrontendConsts(): FrontendConsts {
  const rawConsts = readStorageValue(CONSTS_STORAGE_KEY);

  if (!rawConsts) {
    return {};
  }

  try {
    return JSON.parse(rawConsts) as FrontendConsts;
  } catch {
    return {};
  }
}

function refreshFrontendConsts(meta?: ResponseMeta | null): void {
  if (!meta?.const_hash) {
    return;
  }

  writeStorageValue(CONST_HASH_STORAGE_KEY, meta.const_hash);

  if (meta.consts) {
    writeStorageValue(CONSTS_STORAGE_KEY, JSON.stringify(meta.consts));
  }
}

function buildHeaders(headersInit: HeadersInit | undefined, hasJsonBody: boolean): Headers {
  const headers = new Headers(headersInit);
  const constHash = getFrontendConstsHash();

  if (constHash) {
    headers.set("X-Frontend-Consts-Hash", constHash);
  }

  if (hasJsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return headers;
}

function buildBody(body: ApiRequestOptions["body"]): BodyInit | null | undefined {
  if (!body || body instanceof FormData || body instanceof URLSearchParams) {
    return body;
  }

  if (typeof body === "string" || body instanceof Blob || body instanceof ArrayBuffer) {
    return body;
  }

  return JSON.stringify(body);
}

export async function apiRequest<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiResponse<T>> {
  const body = buildBody(options.body);
  const response = await fetch(buildApiUrl(path), {
    ...options,
    body,
    headers: buildHeaders(options.headers, typeof body === "string"),
  });
  const payload = (await response.json()) as ApiResponse<T>;

  refreshFrontendConsts(payload.meta);

  if (!response.ok || payload.code !== 0) {
    throw new ApiError(
      payload.message ?? "Request failed.",
      response.status,
      payload.code,
      payload.data,
    );
  }

  return payload;
}
