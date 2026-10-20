/** 当前工作流的任务列表，按游戏板块分组。 */
import clsx from 'clsx';
import { ChevronDown, ListTodo } from 'lucide-react';
import { currentWorkflow, groupsWithLeftover, useStore } from '@/store';
import { TaskItem } from './TaskItem';
import { Tooltip } from './ui/Tooltip';

export function TaskList() {
  const catalog = useStore((s) => s.catalog);
  const tasks = useStore((s) => s.tasks);
  const prefs = useStore((s) => s.prefs);
  const collapsed = prefs.collapsedGroups;
  const toggleGroup = useStore((s) => s.toggleGroupCollapsed);
  const wf = currentWorkflow({ catalog, prefs });

  if (!catalog || !wf) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-text-muted gap-3">
        <ListTodo className="w-12 h-12 opacity-30" />
        <p className="text-sm">正在加载任务目录…</p>
      </div>
    );
  }

  const groups = groupsWithLeftover(wf, catalog, tasks);

  return (
    <div className="flex-1 overflow-y-auto overflow-x-hidden p-3">
      <div key={wf.id} className="space-y-3 animate-fade-in">
        {wf.desc && <p className="px-1 text-xs text-text-muted">{wf.desc}</p>}
        {groups.map((g) => {
          const isCollapsed = collapsed.includes(g.id);
          // 只数有开关的卡（子项开关 / 触发任务），纯选项卡和独立任务不算
          const togglable = g.entries.filter((e) => {
            const t = tasks.find((x) => x.class_name === e.task);
            return !!t && (!!e.enable_key || !!t.trigger);
          });
          const enabledCount = togglable.filter((e) => {
            const t = tasks.find((x) => x.class_name === e.task)!;
            if (e.enable_key) return !!t.config.find((f) => f.key === e.enable_key)?.value;
            return t.enabled;
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
                  {togglable.length > 0 && (
                    <span className="text-[11px] text-text-muted">
                      {enabledCount}/{togglable.length}
                    </span>
                  )}
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
                      <TaskItem key={e.id} workflow={wf} entry={e} task={tasks.find((t) => t.class_name === e.task)} />
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
