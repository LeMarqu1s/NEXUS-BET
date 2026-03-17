import { NextResponse } from "next/server";
import { readFile, writeFile } from "fs/promises";
import { join } from "path";

const DATA_ROOT = process.env.NEXUS_DATA_ROOT || join(process.cwd(), "..");

async function loadState() {
  try {
    const path = join(DATA_ROOT, "dashboard_state.json");
    const raw = await readFile(path, "utf-8");
    return JSON.parse(raw);
  } catch {
    return { autonomous_mode: false, copy_trading_mode: false, last_updated: null };
  }
}

export async function GET() {
  const state = await loadState();
  return NextResponse.json(state);
}
