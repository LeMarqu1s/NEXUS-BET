import { NextRequest, NextResponse } from "next/server";

async function validateToken(token: string): Promise<boolean> {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
  if (!supabaseUrl || !serviceKey) return true;
  try {
    const r = await fetch(
      `${supabaseUrl}/rest/v1/users?dashboard_token=eq.${encodeURIComponent(token)}&is_active=eq.true&select=id`,
      {
        headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
        cache: "no-store",
      }
    );
    const rows = await r.json();
    return Array.isArray(rows) && rows.length > 0;
  } catch {
    return false;
  }
}

export async function GET(request: NextRequest) {
  const token =
    request.cookies.get("nexus_token")?.value ||
    request.nextUrl.searchParams.get("token") ||
    "";

  if (!token || !(await validateToken(token))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ positions: [], trades: [], stats: {} });
  }

  try {
    const [posRes, tradeRes] = await Promise.all([
      fetch(
        `${supabaseUrl}/rest/v1/positions?status=eq.OPEN&select=*&order=opened_at.desc&limit=20`,
        { headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` }, cache: "no-store" }
      ),
      fetch(
        `${supabaseUrl}/rest/v1/trades?select=*&order=created_at.desc&limit=30`,
        { headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` }, cache: "no-store" }
      ),
    ]);

    const positions = await posRes.json();
    const trades = await tradeRes.json();

    const tradeList = Array.isArray(trades) ? trades : [];
    const filled = tradeList.filter((t: { status?: string }) => t.status === "FILLED");
    const wins = filled.filter((t: { pnl_usd?: number }) => (t.pnl_usd || 0) > 0).length;
    const totalPnl = filled.reduce((s: number, t: { pnl_usd?: number }) => s + (t.pnl_usd || 0), 0);

    return NextResponse.json({
      positions: Array.isArray(positions) ? positions : [],
      trades: tradeList.slice(0, 20),
      stats: {
        totalTrades: filled.length,
        wins,
        winRate: filled.length > 0 ? ((wins / filled.length) * 100).toFixed(1) : "—",
        totalPnl: totalPnl.toFixed(2),
      },
    });
  } catch {
    return NextResponse.json({ positions: [], trades: [], stats: {} });
  }
}
