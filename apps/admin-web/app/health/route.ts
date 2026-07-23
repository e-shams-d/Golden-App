export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { status: "ok", service: "admin-web" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
