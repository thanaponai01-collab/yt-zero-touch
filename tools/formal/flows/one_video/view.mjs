export const title = "One video: from paste to a Premiere-ready file (or a clear reason why not)";

const why = { login: "login wall", client: "unreachable stream URL", perm: "removed / geo-blocked", none: "unknown error" };

export const state = (v) => {
  switch (v.phase) {
    case "start": return "You pasted a link";
    case "running": return v.fnAlt ? "Downloading (alternate player client)" : "Downloading";
    case "classify":
    case "decide": return `Attempt failed: ${why[v.cls]}`;
    case "fallback": return v.fbKind === "login" ? "Trying another player client (login wall)" : "Trying another player client (bad stream URL)";
    case "ok": return "Done: file in your folder";
    default: return v.reason === "permanent"
      ? `Stopped: needs you (${why[v.cls]})`
      : "Stopped: all retries used";
  }
};

export const group = (v) => {
  if (v.phase === "ok") return "done";
  if (v.phase === "failed") return "failed";
  if (v.phase === "fallback") return "fallback";
  return "working";
};
export const colors = { done: "teal", failed: "orange", fallback: "purple", working: "blue" };

export const step = (action, from, to) => {
  switch (action) {
    case "Begin": return "app starts the download";
    case "CallMain": return to.phase === "ok" ? "download succeeds" : "download fails";
    case "TakeLoginFallback": return "app tries one other player client [first login wall]";
    case "TakeClientFallback": return "app tries one other player client [first bad stream URL]";
    case "NoFallbackTaken": return null;
    case "CallFallback": return to.phase === "ok" ? "other client succeeds" : "other client also fails";
    case "Decide":
      return to.phase === "running" ? "app waits, then retries" : "app gives up";
    default: return null;
  }
};
