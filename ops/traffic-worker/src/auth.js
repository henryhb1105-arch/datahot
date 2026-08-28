const COOKIE_NAME = "__Host-datahot_admin";
const SESSION_TTL_SECONDS = 12 * 60 * 60;
const MAX_PASSWORD_BYTES = 512;
const encoder = new TextEncoder();

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlToBytes(value) {
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

function hexToBytes(value) {
  if (!/^[a-f0-9]{64}$/i.test(String(value || ""))) return null;
  return Uint8Array.from(String(value).match(/.{2}/g), (pair) => Number.parseInt(pair, 16));
}

function constantTimeEqual(left, right) {
  if (!(left instanceof Uint8Array) || !(right instanceof Uint8Array) || left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

async function hmac(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}

function cookieValue(request) {
  const header = request.headers.get("Cookie") || "";
  for (const entry of header.split(";")) {
    const [name, ...parts] = entry.trim().split("=");
    if (name === COOKIE_NAME) return parts.join("=");
  }
  return "";
}

export async function passwordMatches(password, expectedHash) {
  const bytes = encoder.encode(String(password || ""));
  const expected = hexToBytes(expectedHash);
  if (!expected || bytes.byteLength < 20 || bytes.byteLength > MAX_PASSWORD_BYTES) return false;
  const actual = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return constantTimeEqual(actual, expected);
}

export async function createSessionCookie(env, now = new Date()) {
  if (!env.SESSION_SECRET || String(env.SESSION_SECRET).length < 32) throw new Error("SESSION_SECRET is not configured");
  const expires = Math.floor(now.getTime() / 1000) + SESSION_TTL_SECONDS;
  const payload = String(expires);
  const signature = bytesToBase64Url(await hmac(String(env.SESSION_SECRET), payload));
  return `${COOKIE_NAME}=${payload}.${signature}; Path=/; Max-Age=${SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict`;
}

export function clearSessionCookie() {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}

export async function sessionAuthorized(request, env, now = new Date()) {
  if (!env.SESSION_SECRET || String(env.SESSION_SECRET).length < 32) return false;
  const token = cookieValue(request);
  const separator = token.indexOf(".");
  if (separator < 1) return false;
  const payload = token.slice(0, separator);
  const suppliedSignature = base64UrlToBytes(token.slice(separator + 1));
  const expires = Number.parseInt(payload, 10);
  if (!Number.isFinite(expires) || expires <= Math.floor(now.getTime() / 1000)) return false;
  const expectedSignature = await hmac(String(env.SESSION_SECRET), payload);
  return constantTimeEqual(suppliedSignature, expectedSignature);
}

export const LOGIN_HTML = (message = "") => `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <title>登录 · DataHot 运营后台</title>
  <style>
    :root{color-scheme:light;--bg:#f4f5f2;--panel:#fff;--ink:#18201b;--muted:#68736b;--line:#dfe4df;--green:#0b6b47;--red:#a93636}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(420px,calc(100% - 32px));padding:30px;background:var(--panel);border:1px solid var(--line);border-radius:20px;box-shadow:0 18px 50px rgba(25,48,35,.09)}.brand{display:flex;align-items:center;gap:12px}.mark{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:var(--ink);color:#fff;font-weight:800}.eyebrow{color:var(--green);font-size:12px;font-weight:750;letter-spacing:.08em}h1{margin:2px 0 0;font-size:24px;line-height:1.2}p{margin:18px 0;color:var(--muted)}label{display:block;margin-bottom:7px;font-weight:650}input{width:100%;padding:12px 13px;border:1px solid #c9d0ca;border-radius:10px;background:#fff;color:var(--ink);font:inherit;outline:none}input:focus{border-color:var(--green);box-shadow:0 0 0 3px rgba(11,107,71,.12)}button{width:100%;margin-top:14px;padding:12px;border:0;border-radius:10px;background:var(--green);color:#fff;font:inherit;font-weight:700;cursor:pointer}.error{margin:12px 0 0;color:var(--red)}.note{margin:18px 0 0;padding-top:16px;border-top:1px solid var(--line);font-size:12px}
  </style>
</head>
<body><main class="card"><div class="brand"><div class="mark">DH</div><div><div class="eyebrow">PRIVATE ANALYTICS</div><h1>DataHot 运营后台</h1></div></div><p>请输入保存在这台 Mac 钥匙串中的管理员密码。</p><form action="/login" method="post"><label for="password">后台密码</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus><button type="submit">安全登录</button></form>${message ? `<div class="error" role="alert">${message}</div>` : ""}<p class="note">登录状态仅保存在当前浏览器，12 小时后自动失效。</p></main></body></html>`;
