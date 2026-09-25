// Drive sparkDash's real DecodeBenchManager against a loopback endpoint.
// Usage: node bench_crlf.mjs <repoPath> <port> <outJson>
import { pathToFileURL } from "url";
import fs from "fs";

const [repoPath, portStr, outJson] = process.argv.slice(2);
const port = Number(portStr);

const mod = await import(
  pathToFileURL(`${repoPath}/server/collectors/DecodeBench.js`).href
);
const { DecodeBenchManager } = mod;

const hist = `${outJson}.history.json`;
const active = `${outJson}.active.json`;
const mgr = new DecodeBenchManager(hist, active);

const job = mgr.start({
  sparkId: "crlf-test",
  lanIp: "127.0.0.1",
  port,
  modelId: "fake-crlf-model",
  concurrencies: [1, 2],
  maxTokens: 64,
  promptType: "prose",
  debug: true,
});

const deadline = Date.now() + 120_000;
let cur = mgr.getJob(job.benchId);
while (cur.status === "running" && Date.now() < deadline) {
  await new Promise((r) => setTimeout(r, 300));
  cur = mgr.getJob(job.benchId);
}

fs.writeFileSync(outJson, JSON.stringify(cur, null, 2));
console.log(JSON.stringify({
  status: cur.status,
  error: cur.error,
  results: (cur.results || []).map((w) => ({
    concurrency: w.concurrency,
    streamsOk: w.streamsOk,
    error: w.error,
    aggDecodeTps: w.aggregateDecodeTps,
    meanTtftMs: w.meanTtftMs,
    streams: (w.streams || []).map((s) => ({
      completionTokens: s.completionTokens,
      decodeTokens: s.decodeTokens,
      decodeTps: s.decodeTps,
      ttftMs: s.ttftMs,
      error: s.error,
      usage: s.usage ?? undefined,
      sseEventCount: s.http?.sseEventCount ?? undefined,
      finishReason: s.http?.finishReason ?? undefined,
    })),
  })),
}, null, 2));
process.exit(0);
