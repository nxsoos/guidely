export type User = { id: string; username: string; role: "reader" | "admin" };
export type Doc = {
  id: string;
  filename: string;
  text?: string;
  tags: string[];
  category: string;
  state: string;
  error?: string;
};
export type Source = {
  source_id: string;
  document_id: string;
  filename: string;
  chunk_id: string;
  snippet: string;
  page: number | null;
  section: string;
  score: number;
};
export type Answer = {
  answer: string;
  conversation_id: string;
  references: Source[];
  passages: Source[];
  elapsed_ms: number;
};
export type Message = { question: string; response: Answer };
export type Conversation = { id: string; title: string; messages?: Message[] };
export type Metrics = {
  documents: number;
  chunks: number;
  queries_served: number;
  latency_ms: { median: number | null; p95: number | null };
  counters: Record<string, number>;
  errors: Record<string, number>;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Guidely", "1");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Cannot reach Guidely. Check that the backend is running.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (
      response.status === 401 &&
      !path.endsWith("/login") &&
      !path.endsWith("/me")
    )
      window.dispatchEvent(new Event("guidely-session-expired"));
    throw new ApiError(
      data?.error?.message || "The request failed. Please try again.",
      response.status,
    );
  }
  return data as T;
}

export const body = (value: unknown) => JSON.stringify(value);
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";
