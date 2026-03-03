export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/api/v1') {
      const data = await (await fetch(new URL('/data/v1.json', request.url))).json();
      return Response.json(data);
    }
    return fetch(request);
  }
};
