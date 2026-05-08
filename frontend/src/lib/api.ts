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

export type Investigation = {
  investigation_id: number;
  investigation_name: string;
};

export type InvestigationSummary = Investigation & {
  root_point_id: number | null;
  root_question: string;
  root_status: PointStatus | "";
  point_count: number;
};

export type PointStatus = "idle" | "processing" | "completed" | "failed";

export type PointType = "root" | "trunk" | "order_search";

export type Point = {
  point_id: number;
  point_type: PointType;
  question: string;
  raw_data: Record<string, unknown>;
  conclusion: string;
  parent_point_id: number | null;
  investigation_id: number | null;
  reason: string;
  status: PointStatus;
  error: string;
};

export type InvestigationListData = {
  investigations: InvestigationSummary[];
};

export type InvestigationDetailData = {
  investigation: Investigation;
  points: Point[];
};

export type SetPointData = {
  point: Point;
};

export type ProcessPointData = {
  investigation_id: number;
  point_id: number;
};

export type DeleteChildPointsData = {
  point_id: number;
  deleted_count: number;
  deleted_point_ids: number[];
};

export type DeleteInvestigationData = {
  investigation_id: number;
  deleted_point_count: number;
  deleted_point_ids: number[];
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

export async function getInvestigations(): Promise<InvestigationSummary[]> {
  const response = await apiRequest<InvestigationListData>("/investigations");
  return response.data?.investigations ?? [];
}

export async function getInvestigation(
  investigationId: number,
): Promise<InvestigationDetailData> {
  const response = await apiRequest<InvestigationDetailData>(
    `/investigation_and_its_points/${investigationId}`,
  );

  if (!response.data) {
    throw new ApiError("Investigation response was empty.", 500);
  }

  return response.data;
}

export async function setPoint(request: {
  investigation_id?: number | null;
  point_id?: number | null;
  question: string;
  conclusion: string;
}): Promise<Point> {
  const response = await apiRequest<SetPointData>("/set_point", {
    method: "POST",
    body: request,
  });

  if (!response.data?.point) {
    throw new ApiError("Point response was empty.", 500);
  }

  return response.data.point;
}

export async function processPoint(pointId: number | null): Promise<ProcessPointData> {
  const response = await apiRequest<ProcessPointData>("/process_point_endpoint", {
    method: "POST",
    body: { point_id: pointId },
  });

  if (!response.data) {
    throw new ApiError("Process response was empty.", 500);
  }

  return response.data;
}

export async function deleteChildPoints(pointId: number): Promise<DeleteChildPointsData> {
  const response = await apiRequest<DeleteChildPointsData>(`/delete_child_points/${pointId}`, {
    method: "DELETE",
  });

  if (!response.data) {
    throw new ApiError("Delete child points response was empty.", 500);
  }

  return response.data;
}

export async function deleteInvestigation(
  investigationId: number,
): Promise<DeleteInvestigationData> {
  const response = await apiRequest<DeleteInvestigationData>(
    `/delete_investigation_and_child_points/${investigationId}`,
    {
      method: "DELETE",
    },
  );

  if (!response.data) {
    throw new ApiError("Delete investigation response was empty.", 500);
  }

  return response.data;
}
