import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/health"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow static assets and public paths
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  ) {
    return NextResponse.next();
  }

  // Read token from cookie or ?token= query param
  const token =
    request.cookies.get("nexus_token")?.value ||
    request.nextUrl.searchParams.get("token") ||
    "";

  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";

  // No Supabase config: allow access (local dev)
  if (!supabaseUrl || !serviceKey) {
    const res = NextResponse.next();
    if (request.nextUrl.searchParams.get("token")) {
      res.cookies.set("nexus_token", token, { maxAge: 60 * 60 * 24 * 30 });
    }
    return res;
  }

  // Validate token
  try {
    const r = await fetch(
      `${supabaseUrl}/rest/v1/users?dashboard_token=eq.${encodeURIComponent(token)}&is_active=eq.true&select=id`,
      {
        headers: {
          apikey: serviceKey,
          Authorization: `Bearer ${serviceKey}`,
        },
        cache: "no-store",
      }
    );
    const rows = await r.json();
    if (!Array.isArray(rows) || rows.length === 0) {
      return NextResponse.redirect(new URL("/login?error=invalid", request.url));
    }
    const response = NextResponse.next();
    if (request.nextUrl.searchParams.get("token")) {
      response.cookies.set("nexus_token", token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        maxAge: 60 * 60 * 24 * 30,
        path: "/",
      });
    }
    return response;
  } catch {
    return NextResponse.redirect(new URL("/login?error=server", request.url));
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
