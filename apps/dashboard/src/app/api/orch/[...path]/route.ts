import { NextRequest, NextResponse } from "next/server";
import { expectedToken, getOperatorToken } from "@/lib/auth";

const ORCH = (process.env.ORCHESTRATOR_URL || "http://127.0.0.1:8080").replace(/\/$/, "");

async function proxy(req: NextRequest, path: string[]) {
  const expected = expectedToken();
  if (expected) {
    const tok = await getOperatorToken();
    if (tok !== expected) {
      return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
    }
  }

  const url = new URL(req.url);
  const target = `${ORCH}/${path.join("/")}${url.search}`;
  const headers: Record<string, string> = {
    "content-type": req.headers.get("content-type") || "application/json",
  };
  const op = expected || (await getOperatorToken()) || "";
  if (op && op !== "open") {
    headers.authorization = `Bearer ${op}`;
    headers["x-operator-token"] = op;
  }

  const init: RequestInit = { method: req.method, headers };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = Buffer.from(await req.arrayBuffer());
  }

  const upstream = await fetch(target, init);
  const buf = await upstream.arrayBuffer();
  const out = new NextResponse(buf, { status: upstream.status });
  const ct = upstream.headers.get("content-type");
  if (ct) out.headers.set("content-type", ct);
  return out;
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  return proxy(req, (await ctx.params).path);
}
