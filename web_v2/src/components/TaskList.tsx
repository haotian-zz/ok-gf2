/** 按游戏板块分组的任务列表。 */
import clsx from 'clsx';
import { ChevronDown, ListTodo } from 'lucide-react';
import { groupsWithLeftover, useStore } from '@/store';
import { TaskItem } from './TaskItem';
import { Tooltip } from './ui/Tooltip';

export function TaskList() {
  const catalog = useStore((s) => s.catalog);
  const tasks = useStore((s) => s.tasks);
  const collapsed = useStore((s) => s.prefs.collapsedGroups);
  const toggleGroup = useStore((s) => s.toggleGroupCollapsed);

  if (!catalog) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-text-muted gap-3">
        <ListTodo className="w-12 h-12 opacity-30" />
        <p className="text-sm">正在加载任务目录…</p>
      </div>
    );
  }

  const groups = groupsWithLeftover(catalog, tasks);

  return (
    <div className="flex-1 overflow-y-auto overflow-x-hidden p-3">
      <div className="space-y-3">
        {groups.map((g) => {
          const isCollapsed = collapsed.includes(g.id);
          const enabledCount = g.entries.filter((e) => {
            const t = tasks.find((x) => x.class_name === e.task);
            if (!t) return false;
            if (e.enable_key) return !!t.config.find((f) => f.key === e.enable_key)?.value;
            return t.trigger ? t.enabled : false;
          }).length;
          return (
            <section key={g.id}>
              <Tooltip content={g.desc} side="right">
                <button
                  type="button"
                  onClick={() => toggleGroup(g.id)}
                  className="w-full flex items-center gap-2 px-1 py-1 mb-1.5 text-left select-none group/head"
                >
                  <span className="text-base leading-none w-5 text-center">{g.icon}</span>
                  <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{g.label}</span>
                  <span className="text-[11px] text-text-muted">
                    {enabledCount}/{g.entries.length}
                  </span>
                  <span className="flex-1 h-px bg-border mx-1" />
                  <ChevronDown
                    className={clsx(
                      'w-4 h-4 text-text-muted transition-transform duration-150',
                      isCollapsed && '-rotate-90',
                    )}
                  />
                </button>
              </Tooltip>
              <div
                className="grid transition-[grid-template-rows] duration-150 ease-out"
                style={{ gridTemplateRows: isCollapsed ? '0fr' : '1fr' }}
              >
                <div className={clsx('min-h-0', isCollapsed ? 'overflow-hidden' : 'overflow-visible')}>
                  <div className="space-y-2">
                    {g.entries.map((e) => (
                      <TaskItem key={e.id} entry={e} task={tasks.find((t) => t.class_name === e.task)} />
                    ))}
                  </div>
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
