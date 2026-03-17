import { NextRequest, NextResponse } from "next/server";
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

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const mode = (body.mode || "").toLowerCase();
  const state = await loadState();

  if (mode === "autonomous") {
    state.autonomous_mode = !state.autonomous_mode;
  } else if (mode === "copy_trading") {
    state.copy_trading_mode = !state.copy_trading_mode;
  }

  state.last_updated = new Date().toISOString() + "Z";

  try {
    const path = join(DATA_ROOT, "dashboard_state.json");
    await writeFile(path, JSON.stringify(state, null, 2), "utf-8");
  } catch {}

  return NextResponse.json(state);
}
