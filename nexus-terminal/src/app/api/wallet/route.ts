import { NextResponse } from "next/server";

const POLYMARKET_VALUE_URL = "https://data-api.polymarket.com/value";

export async function GET() {
  const relayer = process.env.RELAYER_API_KEY_ADDRESS;
  if (!relayer) {
    return NextResponse.json({ value: 0, user: "" });
  }
  try {
    const res = await fetch(`${POLYMARKET_VALUE_URL}?user=${relayer}`, {
      next: { revalidate: 30 },
    });
    const data = await res.json();
    if (Array.isArray(data) && data.length > 0) {
      return NextResponse.json(data[0]);
    }
    if (typeof data === "object") {
      return NextResponse.json(data);
    }
    return NextResponse.json({ value: 0, user: relayer });
  } catch {
    return NextResponse.json({ value: 0, user: relayer });
  }
}
