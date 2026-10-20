/** 「添加」面板（沿用 MXU AddTaskPanel）：搜索 + 按游戏板块分组的块按钮，点一下加进当前流程。 */
import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { Check, Plus, Search, X } from 'lucide-react';
import { allGroups, currentWorkflow, useStore } from '@/store';
import { Tooltip } from './ui/Tooltip';

export function AddComponentPanel() {
  const catalog = useStore((s) => s.catalog);
  const tasks = useStore((s) => s.tasks);
  const workflows = useStore((s) => s.workflows);
  const prefs = useStore((s) => s.prefs);
  const setPrefs = useStore((s) => s.setPrefs);
  const addItem = useStore((s) => s.addItem);
  const status = useStore((s) => s.status);
  const [query, setQuery] = useState('');
  const wf = currentWorkflow({ workflows, prefs });
  const running = !!status.running && !!status.current_task;

  const groups = useMemo(() => {
    if (!catalog) return [];
    const q = query.trim().toLowerCase();
    return allGroups(catalog, tasks)
      .map((g) => ({
        ...g,
        components: g.components.filter(
          (c) => !q || c.label.toLowerCase().includes(q) || g.label.toLowerCase().includes(q) || (c.doc ?? '').toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.components.length > 0);
  }, [catalog, tasks, query]);

  if (!catalog || !wf) return null;
  const inWorkflow = new Set(wf.items.map((i) => i.component));

  return (
    <div className="border-t border-border bg-bg-primary flex flex-col max-h-[45vh]">
      <div className="flex items-center gap-2 px-3 pt-2 pb-1">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider whitespace-nowrap">添加到「{wf.label}」</span>
        <div className="relative flex-1 max-w-[260px] ml-2">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索块…"
            className="w-full pl-7 pr-2 py-1 text-xs rounded-md bg-bg-secondary border border-border focus:border-accent outline-none text-text-primary placeholder:text-text-muted"
          />
        </div>
        <span className="text-[11px] text-text-muted hidden md:inline">同一块在一个流程里只能有一份；每块的设置只属于当前流程</span>
        <button
          type="button"
          onClick={() => setPrefs({ showAddPanel: false })}
          className="ml-auto p-1 rounded-md hover:bg-bg-hover text-text-muted"
          title="收起"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="overflow-y-auto px-3 pb-3 space-y-3">
        {groups.length === 0 && <div className="text-xs text-text-muted py-4 text-center">没有匹配的块</div>}
        {groups.map((g) => (
          <div key={g.id}>
            <div className="flex items-center gap-1.5 mb-1.5 text-xs text-text-secondary">
              <span className="text-sm leading-none">{g.icon}</span>
              <span className="font-medium">{g.label}</span>
              {g.desc && <span className="text-text-muted truncate">· {g.desc}</span>}
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] gap-2">
              {g.components.map((c) => {
                const added = inWorkflow.has(c.id);
                const task = tasks.find((t) => t.class_name === c.task);
                const tip = [c.doc, !task ? '任务类未注册' : null, added ? '已经在这个流程里' : null].filter(Boolean).join('\n');
                return (
                  <Tooltip key={c.id} content={tip || null} side="top">
                    <button
                      type="button"
                      disabled={added || running}
                      onClick={() => addItem(c.id)}
                      className={clsx(
                        'relative flex min-w-0 items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors text-left',
                        added || running
                          ? 'bg-bg-secondary/50 text-text-muted border border-border/50 cursor-not-allowed opacity-70'
                          : 'bg-bg-secondary hover:bg-bg-hover text-text-primary border border-border hover:border-accent',
                      )}
                    >
                      {added ? <Check className="w-4 h-4 shrink-0 text-success" /> : <Plus className="w-4 h-4 shrink-0 text-accent" />}
                      <span className="min-w-0 flex-1 whitespace-normal [overflow-wrap:anywhere]">{c.label}</span>
                      {!task && <span className="shrink-0 px-1.5 py-0.5 text-[10px] rounded bg-warning/10 text-warning">未注册</span>}
                    </button>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
