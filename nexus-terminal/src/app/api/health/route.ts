import { NextResponse } from "next/server";

export async function GET() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";

  let scannerStatus = "unknown";
  let lastSignalAt: string | null = null;
  let activeSubscribers = 0;

  if (supabaseUrl && serviceKey) {
    try {
      // Last signal
      const sigRes = await fetch(
        `${supabaseUrl}/rest/v1/signals?select=created_at&order=created_at.desc&limit=1`,
        {
          headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
          cache: "no-store",
        }
      );
      const sigRows = await sigRes.json();
      if (Array.isArray(sigRows) && sigRows.length > 0) {
        lastSignalAt = sigRows[0].created_at;
        const diffMin = (Date.now() - new Date(lastSignalAt!).getTime()) / 60000;
        scannerStatus = diffMin < 5 ? "online" : diffMin < 30 ? "slow" : "offline";
      }

      // Active subscribers
      const usrRes = await fetch(
        `${supabaseUrl}/rest/v1/users?is_active=eq.true&select=id`,
        {
          headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
          cache: "no-store",
        }
      );
      const usrRows = await usrRes.json();
      activeSubscribers = Array.isArray(usrRows) ? usrRows.length : 0;
    } catch {
      scannerStatus = "error";
    }
  }

  return NextResponse.json({
    status: "ok",
    scannerStatus,
    lastSignalAt,
    activeSubscribers,
    ts: new Date().toISOString(),
  });
}
