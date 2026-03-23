import { NextRequest, NextResponse } from "next/server";

async function validateToken(token: string): Promise<boolean> {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
  if (!supabaseUrl || !serviceKey) return true; // dev mode
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
    return NextResponse.json({ signals: [] });
  }

  try {
    const limit = Math.min(
      parseInt(request.nextUrl.searchParams.get("limit") || "50", 10),
      100
    );
    const r = await fetch(
      `${supabaseUrl}/rest/v1/signals?select=*&order=created_at.desc&limit=${limit}`,
      {
        headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}` },
        cache: "no-store",
      }
    );
    const signals = await r.json();
    return NextResponse.json({ signals: Array.isArray(signals) ? signals : [] });
  } catch {
    return NextResponse.json({ signals: [] });
  }
}
