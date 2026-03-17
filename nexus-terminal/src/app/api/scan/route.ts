import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";

const DATA_ROOT = process.env.NEXUS_DATA_ROOT || join(process.cwd(), "..");

export async function GET() {
  try {
    const path = join(DATA_ROOT, "paperclip_pending_signals.json");
    const raw = await readFile(path, "utf-8");
    const data = JSON.parse(raw);
    const signals = data?.signals ?? (Array.isArray(data) ? data : []);
    return NextResponse.json({ signals, count: signals.length });
  } catch {
    return NextResponse.json({ signals: [], count: 0 });
  }
}
