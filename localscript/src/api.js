const BASE = '/api';

export async function createSession() {
  const res = await fetch(`${BASE}/chat/sessions`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${BASE}/chat/sessions`);
  if (!res.ok) throw new Error('Failed to list sessions');
  return res.json();
}

export async function getMessages(sessionId) {
  const res = await fetch(`${BASE}/chat/sessions/${sessionId}/messages`);
  if (!res.ok) throw new Error('Failed to get messages');
  return res.json();
}

export async function sendMessage(sessionId, content) {
  const res = await fetch(`${BASE}/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error('Failed to send message');
  return res.json();
}

export async function getGpuStats() {
  const res = await fetch(`${BASE}/gpu/stats`);
  if (!res.ok) return { available: false, gpus: [] };
  return res.json();
}

export async function resetGpuPeak() {
  const res = await fetch(`${BASE}/gpu/reset-peak`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to reset peak');
  return res.json();
}
