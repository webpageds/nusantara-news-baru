// Article-specific Open Graph HTML for WhatsApp and other link-preview crawlers.
// Deploy as Supabase Edge Function "article-share". See admin/README.md.
const SITE_URL = "https://nusantaranewsidn.com";
const FALLBACK_IMAGE = SITE_URL + "/assets/nusantaranews-share.svg";
function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c] as string));
}
function safeImage(value: unknown): string {
  try { const image = new URL(String(value ?? "")); return image.protocol === "https:" ? image.href : FALLBACK_IMAGE; }
  catch { return FALLBACK_IMAGE; }
}
Deno.serve(async request => {
  if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
  const requestUrl = new URL(request.url);
  const pathSlug = requestUrl.pathname.split("/").filter(Boolean).slice(-1)[0] || "";
  const slug = (requestUrl.searchParams.get("slug") || (pathSlug !== "article-share" ? pathSlug : "")).trim();
  if (!slug || slug.length > 180) return new Response("Invalid slug", { status: 400 });
  const projectUrl = Deno.env.get("SUPABASE_URL");
  const publicKey = Deno.env.get("SUPABASE_ANON_KEY") || Deno.env.get("SUPABASE_PUBLISHABLE_KEY");
  if (!projectUrl || !publicKey) return new Response("Preview service not configured", { status: 503 });
  const endpoint = new URL("/rest/v1/articles", projectUrl);
  endpoint.searchParams.set("select", "slug,title,excerpt,image_url");
  endpoint.searchParams.set("slug", "eq." + slug);
  endpoint.searchParams.set("status", "eq.published");
  endpoint.searchParams.set("limit", "1");
  const response = await fetch(endpoint, { headers: { apikey: publicKey, Authorization: "Bearer " + publicKey, Accept: "application/json" } });
  if (!response.ok) return new Response("Preview unavailable", { status: 502 });
  const rows = await response.json();
  const article = Array.isArray(rows) ? rows[0] : null;
  if (!article) return new Response("Article not found", { status: 404 });
  const title = String(article.title || "NusantaraNews"), description = String(article.excerpt || title), image = safeImage(article.image_url);
  const articleUrl = SITE_URL + "/artikel/" + encodeURIComponent(article.slug) + "/";
  // GitHub Pages is static: a newly published Supabase article may not have its\n  // /artikel/{slug}/ file until the scheduled page builder runs. Send readers\n  // to the live Supabase-backed article page immediately; keep the canonical\n  // URL in Open Graph metadata for the generated static page.\n  const landingUrl = SITE_URL + "/article.html?slug=" + encodeURIComponent(article.slug);
  const html = `<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)} | NusantaraNews</title><meta name="description" content="${esc(description)}"><link rel="canonical" href="${esc(articleUrl)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="NusantaraNews"><meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}"><meta property="og:url" content="${esc(articleUrl)}"><meta property="og:image" content="${esc(image)}"><meta property="og:image:secure_url" content="${esc(image)}"><meta property="og:image:alt" content="${esc(title)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="${esc(title)}"><meta name="twitter:description" content="${esc(description)}"><meta name="twitter:image" content="${esc(image)}"><meta http-equiv="refresh" content="0;url=${esc(landingUrl)}"></head><body><p><a href="${esc(articleUrl)}">Buka berita di NusantaraNews</a></p><script>location.replace(${JSON.stringify(landingUrl)});</script></body></html>`;
  return new Response(request.method === "HEAD" ? null : html, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=60, s-maxage=300", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin" } });
});
