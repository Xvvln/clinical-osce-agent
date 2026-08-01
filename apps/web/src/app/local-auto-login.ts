const LOCAL_AUTO_LOGIN_SUPPRESSION_KEY = "clinical-osce:local-auto-login-suppressed";

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "removeItem" | "setItem">;

export function isLocalAutoLoginSuppressed(storage: StorageReader): boolean {
  try {
    return storage.getItem(LOCAL_AUTO_LOGIN_SUPPRESSION_KEY) === "true";
  } catch {
    return false;
  }
}

export function suppressLocalAutoLogin(storage: StorageWriter): void {
  try {
    storage.setItem(LOCAL_AUTO_LOGIN_SUPPRESSION_KEY, "true");
  } catch {
    // Logout must still complete when browser storage is unavailable.
  }
}

export function clearLocalAutoLoginSuppression(storage: StorageWriter): void {
  try {
    storage.removeItem(LOCAL_AUTO_LOGIN_SUPPRESSION_KEY);
  } catch {
    // A successful manual login must not fail because storage is unavailable.
  }
}
