/**
 * Cloudflare Worker — прокси для OpenRouter API.
 *
 * Secrets (устанавливаются через wrangler secret put или Cloudflare Dashboard):
 *   OPENROUTER_API_KEY — ваш ключ OpenRouter
 *   WORKER_SECRET     — произвольный токен для защиты Worker от посторонних
 *
 * Клиент обязан передавать заголовок:
 *   X-Worker-Secret: <значение WORKER_SECRET>
 */

const OPENROUTER_BASE = "https://openrouter.ai/api/v1";

export default {
  async fetch(request, env) {
    // Проверка секретного токена
    const clientSecret = request.headers.get("X-Worker-Secret");
    if (!clientSecret || clientSecret !== env.WORKER_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    const url = new URL(request.url);

    // Строим URL к OpenRouter: убираем префикс /proxy и подставляем реальный путь
    const targetPath = url.pathname.replace(/^\/proxy/, "") + url.search;
    const targetUrl = OPENROUTER_BASE + targetPath;

    // Копируем заголовки, заменяем Authorization на реальный ключ
    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${env.OPENROUTER_API_KEY}`);
    headers.delete("X-Worker-Secret"); // не пересылаем внутренний токен
    headers.set("HTTP-Referer", "https://github.com/ntsay2103-ux/ai-marketing-os");
    headers.set("X-Title", "AI Marketing OS");

    const upstream = new Request(targetUrl, {
      method:  request.method,
      headers: headers,
      body:    request.method !== "GET" && request.method !== "HEAD"
               ? request.body
               : undefined,
    });

    const response = await fetch(upstream);

    // Прозрачно пробрасываем ответ (включая streaming)
    return new Response(response.body, {
      status:     response.status,
      statusText: response.statusText,
      headers:    response.headers,
    });
  },
};
