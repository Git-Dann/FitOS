/**
 * Better Auth's HTTP surface, including the JWKS the API verifies against.
 *
 * Everything under /api/auth is Better Auth's; nothing else in the web app
 * issues or inspects tokens.
 */
import { auth } from "@/lib/auth";

export const GET = (request: Request) => auth.handler(request);
export const POST = (request: Request) => auth.handler(request);
