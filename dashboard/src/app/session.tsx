import { createContext, useContext, type ReactNode } from "react";
import type { SignedIn } from "../auth/smart";

const SessionContext = createContext<SignedIn | null>(null);

export function SessionProvider({ session, children }: { session: SignedIn; children: ReactNode }) {
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

/** Only components rendered under a signed-in session can fetch (R1). */
export function useSession(): SignedIn {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession outside a signed-in session");
  return session;
}
