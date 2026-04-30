export type AuthUser = Readonly<{
  user_id: string;
  email: string;
  display_name: string;
  created_at: string;
}>;

type AuthResponse = Readonly<{
  user: AuthUser;
}>;

type AuthErrorPayload = Readonly<{
  detail?: unknown;
}>;

async function getErrorMessage(response: Response): Promise<string> {
  const detail = await response.text();
  if (!detail) {
    return `请求失败：${response.status}`;
  }

  try {
    const payload = JSON.parse(detail) as AuthErrorPayload;
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    return detail;
  }

  return detail;
}

async function requestAuth<TResponse>(path: string, init: RequestInit): Promise<TResponse> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return (await response.json()) as TResponse;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await fetch("/api/auth/me", {
    credentials: "same-origin",
    method: "GET",
  });

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const payload = (await response.json()) as AuthResponse;
  return payload.user;
}

export async function loginUser(email: string, password: string): Promise<AuthUser> {
  const payload = await requestAuth<AuthResponse>("/api/auth/login", {
    body: JSON.stringify({ email, password }),
    method: "POST",
  });

  return payload.user;
}

export async function registerUser(email: string, password: string, displayName: string): Promise<AuthUser> {
  const payload = await requestAuth<AuthResponse>("/api/auth/register", {
    body: JSON.stringify({ email, password, display_name: displayName }),
    method: "POST",
  });

  return payload.user;
}

export async function logoutUser(): Promise<void> {
  await requestAuth<{ status: string }>("/api/auth/logout", {
    method: "POST",
  });
}
