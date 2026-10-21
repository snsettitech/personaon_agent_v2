// Behind Cloud Run/GCLB, each hop APPENDS to X-Forwarded-For — the last entry
// is the IP the load balancer actually observed (untamperable), while any
// earlier entries are copied verbatim from the client and are spoofable. Take
// the last entry, never the first, or per-IP rate limiting is trivially
// bypassed by sending a fresh spoofed header on every request.
export function clientIp(req: Request): string {
  const fwd = req.headers.get('x-forwarded-for');
  if (fwd) {
    const hops = fwd.split(',').map((hop) => hop.trim()).filter(Boolean);
    if (hops.length > 0) return hops[hops.length - 1];
  }
  return req.headers.get('x-real-ip') || 'local';
}
