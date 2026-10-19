import { NextRequest, NextResponse } from "next/server";
import { TOKEN_COOKIE, expectedToken } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { token?: string };
  const expected = expectedToken();
  const token = (body.token || "").trim();

  if (expected && token !== expected) {
    return NextResponse.json({ ok: false, detail: "invalid token" }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(TOKEN_COOKIE, expected || token || "open", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
