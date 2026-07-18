import dashboardHtml from "../sb_energy_dashboard_modern.html?raw";

const TITLE = "SB Energy Operations Dashboard";
const DESCRIPTION =
  "Run and review SBE Innovation Center photovoltaic performance simulations, comparisons, and export-ready results.";

function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export async function GET(request: Request): Promise<Response> {
  const origin = new URL(request.url).origin;
  const imageUrl = `${origin}/og.png`;
  const socialMetadata = `
    <meta name="description" content="${escapeAttribute(DESCRIPTION)}">
    <meta property="og:type" content="website">
    <meta property="og:title" content="${escapeAttribute(TITLE)}">
    <meta property="og:description" content="${escapeAttribute(DESCRIPTION)}">
    <meta property="og:url" content="${escapeAttribute(`${origin}/`)}">
    <meta property="og:image" content="${escapeAttribute(imageUrl)}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${escapeAttribute(TITLE)}">
    <meta name="twitter:description" content="${escapeAttribute(DESCRIPTION)}">
    <meta name="twitter:image" content="${escapeAttribute(imageUrl)}">
  `;
  const html = dashboardHtml.replace("</head>", `${socialMetadata}</head>`);

  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Referrer-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
