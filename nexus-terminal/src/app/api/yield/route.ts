import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { join } from "path";

const DATA_ROOT = process.env.NEXUS_DATA_ROOT || join(process.cwd(), "..");

export async function GET() {
  try {
    const path = join(DATA_ROOT, "defi_yield_state.json");
    const raw = await readFile(path, "utf-8");
    const data = JSON.parse(raw);
    return NextResponse.json({
      total_usdc: data?.total_usdc ?? 0,
      deposited_aave: data?.deposited_aave ?? 0,
      apy: data?.apy ?? 2,
      yield_generated_usd: data?.yield_generated_usd ?? 0,
      yield_generated_today: data?.yield_generated_today ?? 0,
      mode: data?.mode ?? "yielding",
      last_updated: data?.last_updated,
    });
  } catch {
    return NextResponse.json({
      total_usdc: 0,
      deposited_aave: 0,
      apy: 2,
      yield_generated_usd: 0,
      yield_generated_today: 0,
      mode: "yielding",
      last_updated: null,
    });
  }
}
