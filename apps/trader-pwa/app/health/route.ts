export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { status: "ok", service: "trader-pwa" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
