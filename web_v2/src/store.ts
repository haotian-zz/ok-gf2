import { create } from 'zustand';
import { toast } from 'sonner';
import {
  endpoints,
  eventsUrl,
  type Catalog,
  type CatalogEntry,
  type CatalogGroup,
  type ConfigField,
  type ExecutorStatus,
  type SettingsGroup,
  type TaskInfo,
} from './api';
import {
  applyTheme,
  loadThemeState,
  resolveThemeMode,
  saveThemeState,
  type ThemePreference,
} from './themes';

export type Page = 'main' | 'settings';

export interface LogLine {
  id: number;
  time: string;
  level: string;
  message: string;
}

export interface DailyInfo {
  done: string[];
  retry: string[];
  raw: Record<string, unknown>;
}

interface UiPrefs {
  expanded: string[];
  collapsedGroups: string[];
  rightPanelWidth: number;
  sidePanelExpanded: boolean;
  screenshotExpanded: boolean;
  statusExpanded: boolean;
  showPresetPanel: boolean;
}

const PREFS_KEY = 'okgf2.ui';

function loadPrefs(): UiPrefs {
  const base: UiPrefs = {
    expanded: [],
    collapsedGroups: [],
    rightPanelWidth: 380,
    sidePanelExpanded: true,
    screenshotExpanded: true,
    statusExpanded: true,
    showPresetPanel: false,
  };
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...base, ...(JSON.parse(raw) as Partial<UiPrefs>) };
  } catch {
    /* ignore */
  }
  return base;
}

function savePrefs(p: UiPrefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

const LOG_NOISE = /ocr_zone|detected but no match|emit_draw|find_feature|wait_until timeout/;
const LOG_RE = /^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ (\w+) \S+ (?:\S+?:)?(.*)$/;

function parseLogs(text: string): LogLine[] {
  const out: LogLine[] = [];
  let id = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    const m = line.match(LOG_RE);
    if (m) {
      if (m[3] === 'DEBUG' || LOG_NOISE.test(m[4])) continue;
      out.push({ id: id++, time: m[2], level: m[3], message: m[4] });
    } else if (out.length) {
      out[out.length - 1].message += `\n${line}`;
    } else {
      out.push({ id: id++, time: '', level: 'INFO', message: line });
    }
  }
  return out.slice(-1500);
}

interface State {
  ready: boolean;
  connectionError: string | null;
  title: string;
  catalog: Catalog | null;
  tasks: TaskInfo[];
  settings: SettingsGroup[];
  status: ExecutorStatus;
  logs: LogLine[];
  logLevel: string;
  logQuery: string;
  page: Page;
  prefs: UiPrefs;
  themePreference: ThemePreference;
  accent: string;
  screenshotUrl: string | null;
  screenshotError: string | null;
  streaming: boolean;
  busy: boolean;

  init: () => Promise<void>;
  refreshAll: () => Promise<void>;
  refreshTasks: () => Promise<void>;
  refreshStatus: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  refreshLogs: () => Promise<void>;
  setLogFilter: (level: string, query: string) => void;
  clearLogs: () => void;

  setPage: (p: Page) => void;
  /** 从设置页跳到任务页并展开某一项 */
  focusEntry: (id: string) => void;
  focusedEntry: string | null;
  setPrefs: (patch: Partial<UiPrefs>) => void;
  toggleExpanded: (id: string) => void;
  setAllExpanded: (expanded: boolean) => void;
  toggleGroupCollapsed: (id: string) => void;
  setThemePreference: (p: ThemePreference) => void;
  setAccent: (a: string) => void;

  setTaskConfig: (taskName: string, key: string, value: unknown) => Promise<void>;
  resetTaskConfig: (taskName: string) => Promise<void>;
  setSetting: (group: string, key: string, value: unknown) => Promise<void>;
  setSettings: (group: string, changes: [string, unknown][]) => Promise<void>;
  resetSetting: (group: string) => Promise<void>;
  applyPreset: (presetId: string) => Promise<void>;
  setAllEnabled: (enabled: boolean) => Promise<void>;
  startTask: (taskName: string) => Promise<void>;
  taskAction: (taskName: string, action: string) => Promise<void>;
  stop: () => Promise<void>;
  togglePause: () => Promise<void>;
  captureOnce: () => Promise<void>;
  setStreaming: (on: boolean) => void;
}

let eventKey: string | null = null;
let refreshTimer: number | null = null;
let streamTimer: number | null = null;

function connectEvents(get: () => State) {
  if (!eventKey) return;
  try {
    const ws = new WebSocket(eventsUrl(eventKey));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data as string) as { event?: string };
        if (
          data.event &&
          ['task', 'task_list_updated', 'executor_paused', 'starting_emulator'].includes(data.event)
        ) {
          if (refreshTimer) window.clearTimeout(refreshTimer);
          refreshTimer = window.setTimeout(() => {
            get().refreshAll().catch(() => {});
          }, 300);
        }
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {

      window.setTimeout(() => connectEvents(get), 3000);
    };
  } catch {
    /* ignore */
  }
}

export const useStore = create<State>((set, get) => {
  const theme = loadThemeState();
  applyTheme(resolveThemeMode(theme.preference), theme.accent);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const s = get();
    if (s.themePreference === 'system') applyTheme(resolveThemeMode('system'), s.accent);
  });

  return {
    ready: false,
    connectionError: null,
    title: '少前2 自动化',
    catalog: null,
    tasks: [],
    settings: [],
    status: {},
    logs: [],
    logLevel: 'ALL',
    logQuery: '',
    page: 'main',
    prefs: loadPrefs(),
    themePreference: theme.preference,
    accent: theme.accent,
    screenshotUrl: null,
    screenshotError: null,
    streaming: false,
    busy: false,

    async init() {
      try {
        const [catalog, ui] = await Promise.all([endpoints.catalog(), endpoints.ui()]);
        eventKey = ui.event_session_key ?? null;
        set({ catalog, title: ui.title || '少前2 自动化', connectionError: null });
        document.title = ui.title || '少前2 自动化';
        await get().refreshAll();
        set({ ready: true });
        connectEvents(get);
        get().refreshLogs().catch(() => {});
        window.setInterval(() => {
          get().refreshLogs().catch(() => {});
          get().refreshStatus().catch(() => {});
          // 运行中时任务的 info（当前子任务/今日已完成）会变，没有事件推送也要跟上
          if (get().status.running) get().refreshTasks().catch(() => {});
        }, 2000);
      } catch (err) {
        set({ connectionError: (err as Error).message });
        window.setTimeout(() => get().init(), 3000);
      }
    },

    async refreshAll() {
      await Promise.all([get().refreshTasks(), get().refreshStatus(), get().refreshSettings()]);
    },
    async refreshTasks() {
      const tasks = await endpoints.tasks();
      set({ tasks, connectionError: null });
    },
    async refreshStatus() {
      const status = await endpoints.status();
      set({ status, connectionError: null });
    },
    async refreshSettings() {
      const settings = await endpoints.settings();
      set({ settings });
    },
    async refreshLogs() {
      const { logLevel, logQuery } = get();
      const data = await endpoints.logs(logLevel, logQuery);
      set({ logs: parseLogs(data.text || '') });
    },
    setLogFilter(level, query) {
      set({ logLevel: level, logQuery: query });
      get().refreshLogs().catch(() => {});
    },
    clearLogs() {
      set({ logs: [] });
    },

    setPage(page) {
      set({ page });
      if (page === 'settings') get().refreshSettings().catch((e: Error) => toast.error(e.message));
    },
    focusedEntry: null,
    focusEntry(id) {
      const cur = new Set(get().prefs.expanded);
      cur.add(id);
      get().setPrefs({ expanded: [...cur] });
      set({ page: 'main', focusedEntry: id });
      window.setTimeout(() => set({ focusedEntry: null }), 2000);
    },
    setPrefs(patch) {
      const prefs = { ...get().prefs, ...patch };
      savePrefs(prefs);
      set({ prefs });
    },
    toggleExpanded(id) {
      const cur = new Set(get().prefs.expanded);
      if (cur.has(id)) cur.delete(id);
      else cur.add(id);
      get().setPrefs({ expanded: [...cur] });
    },
    setAllExpanded(expanded) {
      const cat = get().catalog;
      if (!cat) return;
      get().setPrefs({
        expanded: expanded ? cat.groups.flatMap((g) => g.entries.map((e) => e.id)) : [],
      });
    },
    toggleGroupCollapsed(id) {
      const cur = new Set(get().prefs.collapsedGroups);
      if (cur.has(id)) cur.delete(id);
      else cur.add(id);
      get().setPrefs({ collapsedGroups: [...cur] });
    },
    setThemePreference(preference) {
      const accent = get().accent;
      saveThemeState({ preference, accent });
      applyTheme(resolveThemeMode(preference), accent);
      set({ themePreference: preference });
    },
    setAccent(accent) {
      const preference = get().themePreference;
      saveThemeState({ preference, accent });
      applyTheme(resolveThemeMode(preference), accent);
      set({ accent });
    },

    async setTaskConfig(taskName, key, value) {
      try {
        const updated = await endpoints.setTaskConfig(taskName, key, value);
        set({ tasks: get().tasks.map((t) => (t.class_name === updated.class_name ? updated : t)) });
      } catch (err) {
        toast.error(`保存失败：${(err as Error).message}`);
        throw err;
      }
    },
    async resetTaskConfig(taskName) {
      try {
        await endpoints.resetTaskConfig(taskName);
        await get().refreshTasks();
        toast.success('已恢复默认');
      } catch (err) {
        toast.error(`失败：${(err as Error).message}`);
      }
    },
    async setSetting(group, key, value) {
      try {
        const updated = await endpoints.setSetting(group, key, value);
        set({ settings: get().settings.map((g) => (g.name === updated.name ? updated : g)) });
      } catch (err) {
        toast.error(`保存失败：${(err as Error).message}`);
      }
    },
    async setSettings(group, changes) {
      try {
        let updated: SettingsGroup | null = null;
        for (const [key, value] of changes) updated = await endpoints.setSetting(group, key, value);
        if (updated) {
          const u = updated;
          set({ settings: get().settings.map((g) => (g.name === u.name ? u : g)) });
        }
      } catch (err) {
        toast.error(`保存失败：${(err as Error).message}`);
      }
    },
    async resetSetting(group) {
      try {
        await endpoints.resetSetting(group);
        await get().refreshSettings();
        toast.success('已恢复默认');
      } catch (err) {
        toast.error(`失败：${(err as Error).message}`);
      }
    },
    async applyPreset(presetId) {
      const { catalog } = get();
      if (!catalog) return;
      const preset = catalog.presets.find((p) => p.id === presetId);
      const daily = dailyTask(get());
      if (!preset || !daily) {
        toast.error('一键日常任务没有注册');
        return;
      }
      const want = new Set(preset.entries);
      let changed = 0;
      try {
        for (const e of dailyEntries(catalog)) {
          const f = fieldOf(daily, e.enable_key!);
          const target = want.has(e.id);
          if (f && !!f.value !== target) {
            await endpoints.setTaskConfig(daily.name, e.enable_key!, target);
            changed++;
          }
        }
        await get().refreshTasks();
        toast.success(`已应用「${preset.label}」，改了 ${changed} 项`);
      } catch (err) {
        toast.error(`应用预设失败：${(err as Error).message}`);
      }
    },
    async setAllEnabled(enabled) {
      const { catalog } = get();
      const daily = dailyTask(get());
      if (!catalog || !daily) return;
      try {
        for (const e of dailyEntries(catalog)) {
          const f = fieldOf(daily, e.enable_key!);
          if (f && !!f.value !== enabled) {
            await endpoints.setTaskConfig(daily.name, e.enable_key!, enabled);
          }
        }
        await get().refreshTasks();
      } catch (err) {
        toast.error(`保存失败：${(err as Error).message}`);
      }
    },
    async startTask(taskName) {
      set({ busy: true });
      try {
        await endpoints.startTask(taskName);
        toast.success(`已启动「${taskName}」`);
        await get().refreshAll();
      } catch (err) {
        toast.error(`启动失败：${(err as Error).message}`);
      } finally {
        set({ busy: false });
      }
    },
    async taskAction(taskName, action) {
      try {
        await endpoints.taskAction(taskName, action);
        await get().refreshAll();
      } catch (err) {
        toast.error(`失败：${(err as Error).message}`);
      }
    },
    async stop() {
      set({ busy: true });
      try {
        await endpoints.stop();
        toast.info('已发送停止');
        await get().refreshAll();
      } catch (err) {
        toast.error(`停止失败：${(err as Error).message}`);
      } finally {
        set({ busy: false });
      }
    },
    async togglePause() {
      try {
        if (get().status.paused) await endpoints.resume();
        else await endpoints.pause();
        await get().refreshAll();
      } catch (err) {
        toast.error(`操作失败：${(err as Error).message}`);
      }
    },
    async captureOnce() {
      try {
        const r = await endpoints.capture();
        set({
          screenshotUrl: r.resource_url || `/api/capture/image?t=${Date.now()}`,
          screenshotError: null,
        });
      } catch (err) {
        set({ screenshotError: (err as Error).message });
      }
    },
    setStreaming(on) {
      if (streamTimer) {
        window.clearInterval(streamTimer);
        streamTimer = null;
      }
      set({ streaming: on });
      if (on) {
        get().captureOnce().catch(() => {});
        streamTimer = window.setInterval(() => get().captureOnce().catch(() => {}), 3000);
      }
    },
  };
});

// ---------- 派生数据 ----------

export function taskByClass(s: Pick<State, 'tasks'>, cls: string): TaskInfo | undefined {
  return s.tasks.find((t) => t.class_name === cls);
}

export function dailyTask(s: Pick<State, 'tasks' | 'catalog'>): TaskInfo | undefined {
  return s.catalog ? taskByClass(s, s.catalog.daily_task) : undefined;
}

export function fieldOf(task: TaskInfo | undefined, key: string): ConfigField | undefined {
  return task?.config.find((f) => f.key === key);
}

/** 挂在一键日常下、有开关键的条目 */
export function dailyEntries(catalog: Catalog): CatalogEntry[] {
  return catalog.groups
    .flatMap((g) => g.entries)
    .filter((e) => e.task === catalog.daily_task && !!e.enable_key);
}

/** 日常任务里没被任何板块/全局区收编的键，自动收进「其它」组，保证一项都不丢 */
export function groupsWithLeftover(catalog: Catalog, tasks: TaskInfo[]): CatalogGroup[] {
  const daily = tasks.find((t) => t.class_name === catalog.daily_task);
  const groups = catalog.groups.filter((g) => g.id !== '_other');
  if (!daily) return groups;
  const covered = new Set<string>();
  for (const g of catalog.groups)
    for (const e of g.entries) {
      if (e.task !== catalog.daily_task) continue;
      if (e.enable_key) covered.add(e.enable_key);
      if (Array.isArray(e.keys)) e.keys.forEach((k) => covered.add(k));
    }
  for (const s of catalog.global_sections)
    if (s.task === catalog.daily_task) s.keys.forEach((k) => covered.add(k));
  const leftover = daily.config.map((f) => f.key).filter((k) => !covered.has(k));
  if (!leftover.length) return groups;
  return [
    ...groups,
    {
      id: '_other',
      label: '其它日常选项',
      icon: '📦',
      desc: '目录里还没归类的日常配置项。',
      entries: [
        {
          id: '_other',
          label: '未归类的选项',
          task: catalog.daily_task,
          enable_key: null,
          keys: leftover,
          doc: '这些键在 catalog.json 里还没分到板块，先放在这里，不会丢。',
        },
      ],
    },
  ];
}

export function dailyInfo(s: Pick<State, 'tasks' | 'catalog'>): DailyInfo {
  const daily = dailyTask(s);
  const info = (daily?.info ?? {}) as Record<string, unknown>;
  const findList = (needle: string): string[] => {
    const k = Object.keys(info).find((x) => x.includes(needle));
    const v = k ? info[k] : undefined;
    return Array.isArray(v) ? (v as string[]) : [];
  };
  return { done: findList('今日已完成'), retry: findList('今日待重试'), raw: info };
}

/** 条目的选项键列表（enable_key 之外的） */
export function entryOptionKeys(entry: CatalogEntry, task: TaskInfo | undefined): string[] {
  if (!task) return [];
  if (entry.keys === '*') return task.config.map((f) => f.key).filter((k) => k !== entry.enable_key);
  return entry.keys;
}

// ---------- 阵容场景（全局「阵容与助战」里的 <场景>编队 / <场景>助战） ----------
// 优先级：内置默认 → 全局值 → 场景单独设置；场景留空 / 「沿用全局」就继承

export const LINEUP_GROUP = '阵容与助战';
export const LINEUP_PRESET = '编队名';
export const LINEUP_SUPPORT = '借好友助战';
export const SUPPORT_INHERIT = '沿用全局';

export interface ScopeState {
  scope: string;
  preset: string;
  globalPreset: string;
  effectivePreset: string;
  /** null = 这个场景不支持借助战 */
  support: string | null;
  globalSupport: boolean;
  effectiveSupport: boolean | null;
  overridden: boolean;
}

export function lineupGroup(settings: SettingsGroup[]): SettingsGroup | undefined {
  return settings.find((g) => g.name === LINEUP_GROUP);
}

export function lineupField(settings: SettingsGroup[], key: string): ConfigField | undefined {
  return lineupGroup(settings)?.fields.find((f) => f.key === key);
}

/** 有「X编队」键的 X 就是一个场景（「编队名」不以「编队」结尾，不会混进来） */
export function lineupScopes(settings: SettingsGroup[]): string[] {
  const g = lineupGroup(settings);
  return g ? g.fields.filter((f) => f.key.endsWith('编队')).map((f) => f.key.slice(0, -2)) : [];
}

export function isScopeKey(settings: SettingsGroup[], key: string): boolean {
  return lineupScopes(settings).some((s) => key === `${s}编队` || key === `${s}助战`);
}

export function scopeState(settings: SettingsGroup[], scope: string): ScopeState | null {
  const presetField = lineupField(settings, `${scope}编队`);
  if (!presetField) return null;
  const preset = String(presetField.value ?? '').trim();
  const globalPreset = String(lineupField(settings, LINEUP_PRESET)?.value ?? '').trim();
  const supportField = lineupField(settings, `${scope}助战`);
  const support = supportField ? String(supportField.value || SUPPORT_INHERIT) : null;
  const globalSupport = lineupField(settings, LINEUP_SUPPORT)?.value !== false;
  return {
    scope,
    preset,
    globalPreset,
    effectivePreset: preset || globalPreset || '不切编队',
    support,
    globalSupport,
    effectiveSupport: support === null ? null : support === SUPPORT_INHERIT ? globalSupport : support === '开',
    overridden: !!preset || (support !== null && support !== SUPPORT_INHERIT),
  };
}

export function resetScopeChanges(settings: SettingsGroup[], scope: string): [string, unknown][] {
  const changes: [string, unknown][] = [];
  if (lineupField(settings, `${scope}编队`)) changes.push([`${scope}编队`, '']);
  if (lineupField(settings, `${scope}助战`)) changes.push([`${scope}助战`, SUPPORT_INHERIT]);
  return changes;
}

export function entryOfScope(catalog: Catalog, scope: string): CatalogEntry | undefined {
  return catalog.groups.flatMap((g) => g.entries).find((e) => (e.lineup_scopes ?? []).includes(scope));
}
