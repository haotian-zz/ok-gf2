/** ok-script Web 模式自带的 /api 接口的类型与封装。 */

export type FieldKind =
  | 'boolean'
  | 'integer'
  | 'number'
  | 'select'
  | 'list'
  | 'multi_selection'
  | 'multiline'
  | 'file'
  | 'text';

export interface ConfigField {
  key: string;
  value: unknown;
  default?: unknown;
  description?: string;
  kind: FieldKind | string;
  options?: unknown[] | null;
  minimum?: number | null;
  maximum?: number | null;
  sub_config?: boolean;
  allow_duplication?: boolean;
}

export interface TaskInfo {
  name: string;
  class_name: string;
  enabled: boolean;
  running: boolean;
  paused?: boolean;
  trigger?: boolean;
  description?: string;
  info?: Record<string, unknown>;
  config: ConfigField[];
}

export interface SettingsGroup {
  name: string;
  description?: string;
  fields: ConfigField[];
}

export interface ExecutorStatus {
  running?: boolean;
  paused?: boolean;
  starting?: boolean;
  current_task?: string | null;
  [k: string]: unknown;
}

export interface CatalogEntry {
  id: string;
  label: string;
  task: string;
  enable_key: string | null;
  keys: string[] | '*';
  /** 用到的阵容场景（全局「阵容与助战」里的 <场景>编队 / <场景>助战） */
  lineup_scopes?: string[];
  doc?: string;
}

export interface CatalogGroup {
  id: string;
  label: string;
  icon?: string;
  desc?: string;
  entries: CatalogEntry[];
}

export interface CatalogGlobalSection {
  label: string;
  desc?: string;
  task: string;
  keys: string[];
}

export interface CatalogPreset {
  id: string;
  label: string;
  desc?: string;
  entries: string[];
}

export interface Catalog {
  daily_task: string;
  global_sections: CatalogGlobalSection[];
  presets: CatalogPreset[];
  groups: CatalogGroup[];
}

export class ApiError extends Error {}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = (await resp.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail);
  }
  const text = await resp.text();
  return (text ? JSON.parse(text) : null) as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
};

export const taskPath = (name: string) => `/api/tasks/${encodeURIComponent(name)}`;

export const endpoints = {
  catalog: () => api.get<Catalog>('/v2/catalog.json'),
  ui: () => api.get<{ title?: string; event_session_key?: string }>('/api/ui/capture'),
  tasks: () => api.get<TaskInfo[]>('/api/tasks'),
  status: () => api.get<ExecutorStatus>('/api/status'),
  settings: () => api.get<SettingsGroup[]>('/api/settings'),
  logs: (level: string, query: string) =>
    api.get<{ text: string; line_count?: number }>(
      `/api/logs?level=${encodeURIComponent(level)}&query=${encodeURIComponent(query)}`,
    ),
  setTaskConfig: (task: string, key: string, value: unknown) =>
    api.post<TaskInfo>(`${taskPath(task)}/config`, { key, value }),
  resetTaskConfig: (task: string) => api.post<unknown>(`${taskPath(task)}/config/reset`),
  startTask: (task: string) => api.post<unknown>(`${taskPath(task)}/start`),
  taskAction: (task: string, action: string) =>
    api.post<unknown>(`${taskPath(task)}/action`, { action }),
  setSetting: (group: string, key: string, value: unknown) =>
    api.post<SettingsGroup>(`/api/settings/${encodeURIComponent(group)}/config`, { key, value }),
  resetSetting: (group: string) =>
    api.post<unknown>(`/api/settings/${encodeURIComponent(group)}/reset`),
  pause: () => api.post<unknown>('/api/executor/pause'),
  resume: () => api.post<unknown>('/api/executor/resume'),
  stop: () => api.post<unknown>('/api/executor/stop-task'),
  capture: () => api.post<{ resource_url?: string }>('/api/tools/capture'),
};

export function eventsUrl(sessionKey: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${location.host}/api/events?session_key=${encodeURIComponent(sessionKey)}`;
}
