// MSW server shared by the tests. Every request any test makes is recorded, so tests can assert
// on the whole of the app's traffic (R1: nothing before a token; R2: GET only).
import { setupServer } from "msw/node";

export const server = setupServer();

export interface SeenRequest {
  readonly method: string;
  readonly url: string;
  readonly authorization: string | null;
}
export const seen: SeenRequest[] = [];

server.events.on("request:start", ({ request }) => {
  seen.push({ method: request.method, url: request.url, authorization: request.headers.get("authorization") });
});

export function resetSeen(): void {
  seen.length = 0;
}
