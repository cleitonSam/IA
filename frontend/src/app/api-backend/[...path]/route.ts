import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL || "http://localhost:8000";

async function proxy(request: NextRequest, params: { path: string[] }) {
  const path = params.path.join("/");
  const search = request.nextUrl.search;
  const url = `${API_URL}/${path}${search}`;

  const headers = new Headers();
  // Repassa apenas headers relevantes, remove o host para evitar conflitos
  request.headers.forEach((value, key) => {
    if (!["host", "connection"].includes(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const body =
    request.method !== "GET" && request.method !== "HEAD"
      ? await request.arrayBuffer()
      : undefined;

  const response = await fetch(url, {
    method: request.method,
    headers,
    body,
  });

  const resHeaders = new Headers();
  response.headers.forEach((value, key) => {
    resHeaders.set(key, value);
  });

  return new NextResponse(response.body, {
    status: response.status,
    headers: resHeaders,
  });
}

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params);
}
export async function POST(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params);
}
export async function PUT(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params);
}
export async function DELETE(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params);
}
