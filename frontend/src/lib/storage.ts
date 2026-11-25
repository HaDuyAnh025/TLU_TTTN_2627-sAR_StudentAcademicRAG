export const MOCK_STORAGE_PREFIX = "sar_mock_";
const SESSION_ID_KEY = "sar_session_id";
const ADMIN_TOKEN_KEY = "sar_admin_token";

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getStorageItem(key: string): string | null {
  if (!isBrowser()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function setStorageItem(key: string, value: string): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage quota or private-mode errors
  }
}

export function removeStorageItem(key: string): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage access errors
  }
}

export function getJsonStorage<T>(key: string, fallback: T): T {
  const raw = getStorageItem(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function setJsonStorage<T>(key: string, value: T): void {
  try {
    setStorageItem(key, JSON.stringify(value));
  } catch {
    // Ignore serialization errors
  }
}

export function mockStorageKey(name: string): string {
  return name.startsWith(MOCK_STORAGE_PREFIX)
    ? name
    : `${MOCK_STORAGE_PREFIX}${name}`;
}

export function getMockStorage<T>(name: string, fallback: T): T {
  return getJsonStorage<T>(mockStorageKey(name), fallback);
}

export function setMockStorage<T>(name: string, value: T): void {
  setJsonStorage<T>(mockStorageKey(name), value);
}

export function removeMockStorage(name: string): void {
  removeStorageItem(mockStorageKey(name));
}

export function clearAllMockStorage(): void {
  if (!isBrowser()) return;
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(MOCK_STORAGE_PREFIX)) {
        keysToRemove.push(key);
      }
    }
    for (const key of keysToRemove) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Ignore storage access errors
  }
}

export function getOrCreateSessionId(): string {
  if (!isBrowser()) return "";
  const existing = getStorageItem(SESSION_ID_KEY);
  if (existing) return existing;

  const generated =
    typeof window.crypto !== "undefined" &&
    typeof window.crypto.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;

  setStorageItem(SESSION_ID_KEY, generated);
  return generated;
}

export function getAdminToken(): string | null {
  return getStorageItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string): void {
  setStorageItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  removeStorageItem(ADMIN_TOKEN_KEY);
}
