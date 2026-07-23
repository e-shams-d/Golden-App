export type HeaderValue = Readonly<{ key: string; value: string }>;

export function buildSecurityHeaders(options?: {
  enableHsts?: boolean;
  allowDevelopmentEval?: boolean;
}): HeaderValue[];

export function buildNextHeaderRules(options?: {
  enableHsts?: boolean;
  allowDevelopmentEval?: boolean;
  protectedPagePatterns?: string[];
}): Array<Readonly<{ source: string; headers: HeaderValue[] }>>;

export const noStoreHeaders: HeaderValue[];
