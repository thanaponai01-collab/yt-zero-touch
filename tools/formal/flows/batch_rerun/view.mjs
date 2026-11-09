export const title = "Paste page A (two videos) + link B, run it, then run it again after a failure";

const A = ["i1", "i2"];
const n = (v, ids, s) => ids.filter((i) => v.st[i] === s).length;

const pageA = (v) => {
  if (n(v, A, "skipped") === 2) return "A skipped";
  const done = n(v, A, "done"), failed = n(v, A, "failed");
  if (done === 2) return "A both ok";
  if (failed === 2) return "A both failed";
  return "A one ok, one failed";
};
const linkB = (v) => ({ skipped: "B skipped", done: "B ok", failed: "B failed" }[v.st.i3]);

export const state = (v) => {
  const run = `Run ${v.runs}`;
  const ids = ["i1", "i2", "i3"];
  if (ids.some((i) => v.st[i] === "skipped" && !v.got[i]))
    return `${run}: skips a video that was never downloaded`;
  if (ids.some((i) => v.st[i] === "pending")) return `${run}: checking history`;
  if (ids.some((i) => v.st[i] === "queued" || v.st[i] === "downloading")) return `${run}: downloading`;
  return `${run} finished: ${pageA(v)}, ${linkB(v)}`;
};

export const group = (v) => {
  const s = state(v);
  if (s.includes("never downloaded")) return "bug";
  if (s.includes("finished")) return "finished";
  return "working";
};
export const colors = { bug: "orange", finished: "teal", working: "blue" };

export const step = (action) => {
  switch (action) {
    case "RunAgain": return "you run the batch again";
    case "Resolve": return "app checks the history";
    case "Start": return "a download starts";
    case "Succeed": return "a download finishes";
    case "Fail": return "a download fails";
    default: return null;
  }
};
