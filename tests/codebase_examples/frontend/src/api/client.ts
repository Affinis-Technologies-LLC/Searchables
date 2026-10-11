export class Http {
  async get<T>(url: string): Promise<T> {
    const response = await fetch(url);
    return response.json();
  }

  async post<T>(url: string, body: unknown): Promise<T> {
    const response = await fetch(url, { method: 'POST', body: JSON.stringify(body) });
    return response.json();
  }
}

export const http = new Http();
