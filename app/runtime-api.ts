export const LOCAL_PRODUCTION_API = "http://127.0.0.1:3498";

export function isLocalProductionBrowser() {
  if (typeof window === "undefined") return false;
  return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

export function runtimeApiBase() {
  return isLocalProductionBrowser() ? LOCAL_PRODUCTION_API : "";
}

export async function copyProductionPath(path: string) {
  await navigator.clipboard.writeText(path);
}

export function containingDirectory(path: string) {
  const normalized = path.replace(/\/+$/, "");
  const separator = normalized.lastIndexOf("/");
  return separator > 0 ? normalized.slice(0, separator) : normalized;
}
