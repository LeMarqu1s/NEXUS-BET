import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";

const DATA_ROOT = process.env.NEXUS_DATA_ROOT || join(process.cwd(), "..");

export async function GET() {
  try {
    const path = join(DATA_ROOT, "ai_debates_log.json");
    const raw = await readFile(path, "utf-8");
    const data = JSON.parse(raw);
    const debates = data?.debates ?? (Array.isArray(data) ? data : []);
    return NextResponse.json({ debates, count: debates.length });
  } catch {
    return NextResponse.json({ debates: [], count: 0 });
  }
}
