import { expectedToken, getOperatorToken } from "@/lib/auth";

const ORCH = (process.env.ORCHESTRATOR_URL || "http://127.0.0.1:8080").replace(/\/$/, "");

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request) {
  const expected = expectedToken();
  if (expected) {
    const tok = await getOperatorToken();
    if (tok !== expected) {
      return new Response(JSON.stringify({ detail: "unauthorized" }), { status: 401 });
    }
  }

  const url = new URL(req.url);
  const since = url.searchParams.get("since") || "0";
  const headers: HeadersInit = {};
  const op = expected || (await getOperatorToken()) || "";
  if (op && op !== "open") {
    headers["authorization"] = `Bearer ${op}`;
    headers["x-operator-token"] = op;
  }

  const upstream = await fetch(`${ORCH}/events/stream?since=${encodeURIComponent(since)}`, {
    headers,
    // @ts-expect-error Node fetch streaming
    duplex: "half",
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text();
    return new Response(text, { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}
