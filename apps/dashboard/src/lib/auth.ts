import { cookies } from "next/headers";

export const TOKEN_COOKIE = "buildshift_operator_token";

export async function getOperatorToken(): Promise<string | undefined> {
  const jar = await cookies();
  return jar.get(TOKEN_COOKIE)?.value;
}

export function expectedToken(): string {
  return (process.env.OPERATOR_TOKEN || "").trim();
}

export async function isAuthed(): Promise<boolean> {
  const expected = expectedToken();
  if (!expected) return true; // open local mode
  const got = await getOperatorToken();
  return Boolean(got && got === expected);
}
