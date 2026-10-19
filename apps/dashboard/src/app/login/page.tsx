"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      setError("Invalid operator token");
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Buildshift</h1>
        <p>Enter the operator token to enter the office floor.</p>
        <label>
          Operator token
          <input
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="OPERATOR_TOKEN (empty ok if unset)"
          />
        </label>
        {error && <p className="err">{error}</p>}
        <button type="submit">Enter office</button>
      </form>
    </main>
  );
}
