export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL || "http://localhost:8000";
const PROXY_TIMEOUT_MS = 30_000;

async function proxy(request: NextRequest, params: Promise<{ path: string[] }>) {
  const { path } = await params;
  const search = request.nextUrl.search;
  const url = `${API_URL}/${path.join("/")}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!["host", "connection"].includes(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const body =
    request.method !== "GET" && request.method !== "HEAD"
      ? await request.arrayBuffer()
      : undefined;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body,
      signal: controller.signal,
    });

    const resHeaders = new Headers();
    response.headers.forEach((value, key) => {
      resHeaders.set(key, value);
    });

    return new NextResponse(response.body, {
      status: response.status,
      headers: resHeaders,
    });
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return NextResponse.json(
        { error: { code: "GATEWAY_TIMEOUT", message: "Backend não respondeu a tempo" } },
        { status: 504 }
      );
    }

    return NextResponse.json(
      { error: { code: "BAD_GATEWAY", message: "Erro ao conectar com o backend" } },
      { status: 502 }
    );
  } finally {
    clearTimeout(timeout);
  }
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params);
}
export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params);
}
export async function PUT(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params);
}
export async function DELETE(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params);
}
