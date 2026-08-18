/**
 * Better Auth — identity only.
 *
 * ADR 0005 splits identity from authorisation: this issues, FastAPI verifies.
 * ADR 0009 narrows what it may issue. The token carries `sub` and `org` and
 * nothing that describes authority — no role, no capability list — because the
 * API reads those from the membership row on every request. A token that
 * asserted its own role would keep asserting it until it expired.
 *
 * Two details here are load-bearing:
 *
 * - The user model is mapped onto the existing `users` table rather than
 *   getting one of its own. `memberships.user_id` references it, so a second
 *   user table would mean two answers to "who is this" with a foreign key
 *   pointing at only one of them.
 * - `expirationTime` is short. It is no longer a security boundary — authority
 *   is re-read per request — but it still bounds how long a stolen token is
 *   useful for proving identity.
 */
import { betterAuth } from "better-auth";
import { jwt } from "better-auth/plugins";
import { Pool } from "pg";

/** Fail loudly at import time rather than serving with a missing secret. */
function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Identity cannot start without it, and there is no ` +
        `default: a default secret here becomes a production secret.`,
    );
  }
  return value;
}

export const ISSUER = process.env.FITOS_AUTH_ISSUER ?? "http://localhost:3000";
export const AUDIENCE = process.env.FITOS_AUTH_AUDIENCE ?? "fitos-api";

export const auth = betterAuth({
  baseURL: ISSUER,
  secret: required("BETTER_AUTH_SECRET"),
  database: new Pool({ connectionString: required("FITOS_AUTH_DATABASE_URL") }),

  emailAndPassword: { enabled: true },

  user: {
    // The identity mirror the API already owns. See migration 0001.
    modelName: "users",
    fields: {
      name: "display_name",
      emailVerified: "email_verified",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  // Every field is mapped, not just the ones that collide. Better Auth defaults
  // to camelCase column names; leaving them would put quoted identifiers like
  // "expiresAt" next to snake_case everywhere else, and a schema you have to
  // quote is a schema people get wrong.
  session: {
    modelName: "sessions",
    fields: {
      userId: "user_id",
      expiresAt: "expires_at",
      ipAddress: "ip_address",
      userAgent: "user_agent",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  account: {
    modelName: "accounts",
    fields: {
      userId: "user_id",
      accountId: "account_id",
      providerId: "provider_id",
      accessToken: "access_token",
      refreshToken: "refresh_token",
      idToken: "id_token",
      accessTokenExpiresAt: "access_token_expires_at",
      refreshTokenExpiresAt: "refresh_token_expires_at",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  verification: {
    modelName: "verifications",
    fields: {
      expiresAt: "expires_at",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },

  advanced: {
    database: {
      // UUIDs, because every other id in this system is one and
      // memberships.user_id is typed uuid.
      generateId: () => crypto.randomUUID(),
    },
  },

  plugins: [
    jwt({
      schema: {
        jwks: {
          modelName: "jwks",
          fields: {
            publicKey: "public_key",
            privateKey: "private_key",
            createdAt: "created_at",
            expiresAt: "expires_at",
          },
        },
      },
      jwks: {
        // EdDSA/Ed25519 is Better Auth's default and is on the API's
        // allowlist. HS* is not, and cannot be: the JWKS is public, so a
        // symmetric algorithm would let anyone who can read it mint tokens.
        keyPairConfig: { alg: "EdDSA", crv: "Ed25519" },
      },
      jwt: {
        issuer: ISSUER,
        audience: AUDIENCE,
        expirationTime: "15m",
        definePayload: ({ user }) => ({
          // `org` is the organization the caller is asking to act in. It is a
          // request, not a grant — the API still has to find a membership for
          // this user inside it (ADR 0009). Deliberately no role and no
          // capabilities: there is nowhere for them to land on the other side.
          org: (user as { activeOrganizationId?: string }).activeOrganizationId,
        }),
      },
    }),
  ],
});
