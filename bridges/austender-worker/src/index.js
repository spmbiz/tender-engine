const UPSTREAM = "https://www.tenders.gov.au/public_data/rss/rss.xml";

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET") {
      return new Response("method not allowed", { status: 405, headers: { Allow: "GET" } });
    }
    if (url.pathname !== "/rss.xml" && url.pathname !== "/") {
      return new Response("not found", { status: 404 });
    }

    // Keep the relay private when a secret is configured. The secret is set with
    // `wrangler secret put BRIDGE_TOKEN`; it is never committed to the repository.
    if (env.BRIDGE_TOKEN) {
      const expected = `Bearer ${env.BRIDGE_TOKEN}`;
      if (request.headers.get("authorization") !== expected) {
        return new Response("unauthorized", { status: 401 });
      }
    }

    const upstream = await fetch(UPSTREAM, {
      method: "GET",
      headers: {
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.2",
        "User-Agent": "Tender-Engine-AusTender-Relay/1.0",
      },
      cf: { cacheTtl: 300, cacheEverything: true },
    });

    if (!upstream.ok) {
      return new Response(`upstream ${upstream.status}`, {
        status: 502,
        headers: {
          "X-Tender-Engine-Upstream": UPSTREAM,
          "X-Tender-Engine-Upstream-Status": String(upstream.status),
        },
      });
    }

    const bytes = await upstream.arrayBuffer();
    const prefix = new TextDecoder().decode(bytes.slice(0, Math.min(bytes.byteLength, 512))).trimStart();
    const contentType = upstream.headers.get("content-type") || "";
    if (!prefix.startsWith("<?xml") && !prefix.includes("<rss") && !contentType.toLowerCase().includes("xml")) {
      return new Response("upstream payload is not RSS/XML", {
        status: 502,
        headers: { "X-Tender-Engine-Upstream": UPSTREAM },
      });
    }

    const digest = hex(await crypto.subtle.digest("SHA-256", bytes));
    return new Response(bytes, {
      status: 200,
      headers: {
        "Content-Type": contentType || "application/rss+xml; charset=utf-8",
        "Cache-Control": "public, max-age=300",
        "X-Tender-Engine-Upstream": UPSTREAM,
        "X-Tender-Engine-Upstream-Status": String(upstream.status),
        "X-Tender-Engine-SHA256": digest,
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
