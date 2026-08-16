import type { NextRequest } from "next/server";

import { forwardAndIssueCookie } from "@/lib/bff-auth";

export async function POST(request: NextRequest) {
  return forwardAndIssueCookie(request, "/api/v1/auth/mfa/verify", await request.text());
}
