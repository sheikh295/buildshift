import { redirect } from "next/navigation";
import { readFile } from "fs/promises";
import path from "path";
import { isAuthed } from "@/lib/auth";
import { OfficeApp } from "@/components/OfficeApp";
import type { OfficeMap } from "@/lib/types";

export default async function HomePage() {
  if (!(await isAuthed())) {
    redirect("/login");
  }

  const mapPath = path.join(process.cwd(), "public", "office", "map.json");
  const map = JSON.parse(await readFile(mapPath, "utf8")) as OfficeMap;

  return <OfficeApp map={map} />;
}
