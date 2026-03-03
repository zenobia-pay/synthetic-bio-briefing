export interface Env { TRIGGER_WEBHOOK_URL?: string }

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/api/v1') {
      const data = await (await fetch(new URL('/data/v1.json', request.url))).json();
      return Response.json(data);
    }
    if (url.pathname === '/api/run' && request.method === 'POST') {
      const body = await request.json<any>().catch(() => ({}));
      const prompt = body?.prompt || 'Run daily briefing';
      if (!env.TRIGGER_WEBHOOK_URL) return Response.json({ ok:false, error:'Missing webhook secret' }, { status:500 });
      const resp = await fetch(env.TRIGGER_WEBHOOK_URL, { method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({ text: prompt })});
      return Response.json({ ok: resp.ok, status: resp.status });
    }
    return fetch(request);
  }
};
