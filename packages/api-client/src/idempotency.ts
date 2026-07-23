export type CommandSubmissionState =
  | "idle"
  | "submitting"
  | "checking"
  | "completed"
  | "failed";

export type CommandSubmission = Readonly<{
  key: string;
  state: CommandSubmissionState;
}>;

export function createIdempotencyKey(): string {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error("Secure random UUID support is required.");
  }
  return globalThis.crypto.randomUUID();
}

export function createCommandSubmission(
  key = createIdempotencyKey(),
): CommandSubmission {
  return { key, state: "idle" };
}
