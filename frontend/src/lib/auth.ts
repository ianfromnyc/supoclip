import { betterAuth } from "better-auth";
import { prismaAdapter } from "better-auth/adapters/prisma";
import { PrismaClient } from "../generated/prisma";
import { nextCookies } from "better-auth/next-js";
import { computeTrustedOrigins } from "./trusted-origins";

const prisma = new PrismaClient();

// The only values that open public registration. Anything else — including an
// unset variable, an empty string, or a typo — leaves sign-ups closed.
const SIGN_UP_OPT_OUT_VALUES = ["0", "false", "no"];

/**
 * Decides whether self-service registration is closed.
 *
 * Sign-ups are closed unless the operator explicitly opts out, so a deployment
 * that forgets to set DISABLE_SIGN_UP fails safe instead of exposing an open
 * registration form.
 */
export function isSignUpDisabled(value: string | undefined): boolean {
  return !SIGN_UP_OPT_OUT_VALUES.includes((value ?? "").trim().toLowerCase());
}

const disableSignUp = isSignUpDisabled(process.env.DISABLE_SIGN_UP);

const trustedOrigins = computeTrustedOrigins({
  NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
  BETTER_AUTH_URL: process.env.BETTER_AUTH_URL,
  NODE_ENV: process.env.NODE_ENV,
});

export const auth = betterAuth({
  database: prismaAdapter(prisma, {
    provider: "postgresql",
  }),
  user: {
    deleteUser: {
      enabled: true,
    },
    additionalFields: {
      is_admin: {
        type: "boolean",
        input: false,
      },
    },
  },
  trustedOrigins,
  emailAndPassword: {
    enabled: true,
    disableSignUp,
  },
  plugins: [
    nextCookies(), // Enable Next.js cookie handling
  ],
});

export type Session = typeof auth.$Infer.Session;
