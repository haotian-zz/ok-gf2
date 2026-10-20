/** 任务卡片：沿用 MXU TaskItem 的结构（复选框 + 名称 + 选项预览 + 展开面板）。 */
import { useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { ChevronRight, Play, RotateCcw, Zap, ZapOff } from 'lucide-react';
import type { CatalogEntry, ConfigField, TaskInfo } from '@/api';
import { dailyInfo, entryOptionKeys, fieldOf, useStore } from '@/store';
import { Checkbox } from './ui/Checkbox';
import { ConfirmDialog } from './ui/Modal';
import { OptionList } from './OptionEditor';
import { Tooltip } from './ui/Tooltip';
import { LineupCard } from './LineupCard';

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function PreviewTag({ field }: { field: ConfigField }) {
  const v = field.value;
  const text = Array.isArray(v) ? `${v.length} 项` : v === null || v === undefined ? '' : String(v);
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded text-text-tertiary max-w-[140px]"
      title={`${field.key}: ${text}`}
    >
      {field.kind === 'boolean' ? (
        <>
          <span className="truncate">{truncate(field.key, 6)}</span>
          <span
            className={clsx(
              'w-1.5 h-1.5 rounded-full flex-shrink-0',
              v ? 'bg-success/70' : 'bg-text-muted/50',
            )}
          />
        </>
      ) : (
        <>
          <span className="truncate flex-shrink-0">{truncate(field.key, 4)}</span>
          <span className="flex-shrink-0">:</span>
          <span className="truncate">{truncate(text, 6)}</span>
        </>
      )}
    </span>
  );
}

export function TaskItem({ entry, task }: { entry: CatalogEntry; task: TaskInfo | undefined }) {
  const catalog = useStore((s) => s.catalog)!;
  const expanded = useStore((s) => s.prefs.expanded.includes(entry.id));
  const toggleExpanded = useStore((s) => s.toggleExpanded);
  const setTaskConfig = useStore((s) => s.setTaskConfig);
  const resetTaskConfig = useStore((s) => s.resetTaskConfig);
  const startTask = useStore((s) => s.startTask);
  const taskAction = useStore((s) => s.taskAction);
  const status = useStore((s) => s.status);
  const tasks = useStore((s) => s.tasks);
  const di = useMemo(() => dailyInfo({ tasks, catalog }), [tasks, catalog]);
  const [confirmReset, setConfirmReset] = useState(false);
  const focused = useStore((s) => s.focusedEntry === entry.id);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focused) rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focused]);
  const lineupScopesOfEntry = entry.lineup_scopes ?? [];

  const isDaily = task?.class_name === catalog.daily_task;
  const enableField = entry.enable_key ? fieldOf(task, entry.enable_key) : undefined;
  const enabled = entry.enable_key ? !!enableField?.value : isDaily ? true : !!task?.enabled;
  const optionKeys = entryOptionKeys(entry, task);
  const optionFields = optionKeys
    .map((k) => fieldOf(task, k))
    .filter((f): f is ConfigField => !!f);
  const canExpand = !!task && (optionFields.length > 0 || lineupScopesOfEntry.length > 0 || !!entry.doc || !!task.description);
  const executorRunning = !!status.running && !!status.current_task;

  // 运行状态：独立任务看 running；日常子项看「当前任务」是否就是它
  const runStatus: 'idle' | 'running' | 'done' | 'retry' = (() => {
    if (!task) return 'idle';
    if (!isDaily) return task.running ? 'running' : 'idle';
    if (entry.enable_key) {
      if (executorRunning && status.current_task === task.name && di.raw.current_task === entry.enable_key)
        return 'running';
      if (di.done.includes(entry.enable_key)) return 'done';
      if (di.retry.includes(entry.enable_key)) return 'retry';
    }
    return 'idle';
  })();

  const handleCheckbox = () => {
    if (!task) return;
    if (entry.enable_key) void setTaskConfig(task.name, entry.enable_key, !enabled).catch(() => {});
    else if (task.trigger) void taskAction(task.name, task.enabled ? 'disable' : 'enable');
  };

  const checkboxDisabled = !task || (!entry.enable_key && !task.trigger);

  return (
    <div
      ref={rootRef}
      className={clsx(
        'group bg-bg-secondary rounded-lg border border-border transition-shadow relative overflow-hidden',
        runStatus === 'running' && 'task-item-running',
        focused && 'ring-2 ring-accent/60',
      )}
    >
      {runStatus !== 'idle' && (
        <div
          className={clsx(
            'absolute left-0 top-0 bottom-0 w-1.5',
            runStatus === 'running' && 'bg-accent',
            runStatus === 'done' && 'bg-success/60',
            runStatus === 'retry' && 'bg-warning',
          )}
          title={runStatus === 'running' ? '运行中' : runStatus === 'done' ? '今日已完成' : '今日待重试'}
        />
      )}

      <div className="flex items-center gap-2 p-3 pl-4">
        {checkboxDisabled ? (
          <Tooltip content={task ? '独立任务，直接在右侧「运行」' : '任务类未注册'}>
            <span className="w-4 h-4 flex items-center justify-center text-text-muted">
              <Play className="w-3 h-3" />
            </span>
          </Tooltip>
        ) : (
          <Checkbox
            checked={enabled}
            disabled={executorRunning && isDaily}
            title={task?.trigger ? (enabled ? '停用触发任务' : '启用触发任务') : enabled ? '取消勾选' : '勾选加入一键日常'}
            onClick={handleCheckbox}
          />
        )}

        <div className="flex-1 flex items-center min-w-0">
          <div
            className={clsx('flex items-center gap-1 min-w-0 overflow-hidden', !checkboxDisabled && 'cursor-pointer')}
            onClick={() => !checkboxDisabled && handleCheckbox()}
          >
            <span
              className={clsx(
                'min-w-0 text-sm font-medium truncate',
                enabled || checkboxDisabled ? 'text-text-primary' : 'text-text-muted',
              )}
            >
              {entry.label}
            </span>
          </div>

          {!task && (
            <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-warning/10 text-warning">未注册</span>
          )}
          {task && !isDaily && task.trigger && (
            <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-bg-tertiary text-text-tertiary">
              {task.enabled ? <Zap className="w-3 h-3 text-accent" /> : <ZapOff className="w-3 h-3" />}
              触发任务
            </span>
          )}
          {runStatus === 'done' && (
            <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-accent/10 text-accent whitespace-nowrap">今日已完成</span>
          )}
          {runStatus === 'retry' && (
            <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-warning/10 text-warning whitespace-nowrap">待重试</span>
          )}

          {canExpand && (
            <div
              onClick={() => toggleExpanded(entry.id)}
              className="flex-1 min-w-0 flex items-center self-stretch min-h-[28px] cursor-pointer"
              title={expanded ? '收起' : '展开'}
            >
              {!expanded && (
                <div className="flex-1 flex items-center gap-1.5 mx-2 overflow-hidden">
                  {optionFields.slice(0, 4).map((f) => (
                    <PreviewTag key={f.key} field={f} />
                  ))}
                </div>
              )}
              <div className="flex shrink-0 items-center justify-end pl-2 ml-auto">
                <ChevronRight
                  className={clsx(
                    'w-4 h-4 text-text-secondary transition-transform duration-150 ease-out',
                    expanded && 'rotate-90',
                  )}
                />
              </div>
            </div>
          )}
        </div>

        {task && !isDaily && !task.trigger && (
          <button
            type="button"
            onClick={() => startTask(task.name)}
            disabled={executorRunning}
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors shrink-0',
              executorRunning
                ? 'text-text-muted cursor-not-allowed'
                : 'bg-accent/10 text-accent hover:bg-accent hover:text-white',
            )}
            title={`单独运行「${task.name}」`}
          >
            <Play className="w-3 h-3" />
            运行
          </button>
        )}
      </div>

      {canExpand && (
        <div
          className="grid transition-[grid-template-rows] duration-150 ease-out"
          style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
        >
          <div className={clsx('min-h-0', expanded ? 'overflow-visible' : 'overflow-hidden')}>
            <div className="border-t border-border bg-bg-tertiary p-3 rounded-b-lg">
              {(entry.doc || (!isDaily && task?.description)) && (
                <div className={clsx('text-xs text-text-secondary whitespace-pre-line', optionFields.length > 0 && 'mb-4')}>
                  {entry.doc || task?.description}
                </div>
              )}
              {task && optionFields.length > 0 && (
                <OptionList
                  fields={task.config}
                  keys={optionKeys}
                  disabled={executorRunning && isDaily}
                  onChange={(key, value) => setTaskConfig(task.name, key, value).catch(() => {})}
                />
              )}
              {task && lineupScopesOfEntry.length > 0 && (
                <div className={clsx('space-y-3', optionFields.length > 0 && 'mt-4')}>
                  {lineupScopesOfEntry.map((scope) => (
                    <LineupCard key={scope} scope={scope} disabled={executorRunning} />
                  ))}
                </div>
              )}
              {task && (
                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    onClick={() => setConfirmReset(true)}
                    className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-accent transition-colors"
                  >
                    <RotateCcw className="w-3 h-3" />
                    恢复「{task.name}」默认值
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {task && (
        <ConfirmDialog
          open={confirmReset}
          title="恢复默认"
          message={`把「${task.name}」的全部选项恢复默认？${isDaily ? '\n这会影响其它板块里属于一键日常的项。' : ''}`}
          confirmText="恢复"
          destructive
          onCancel={() => setConfirmReset(false)}
          onConfirm={() => {
            setConfirmReset(false);
            void resetTaskConfig(task.name);
          }}
        />
      )}
    </div>
  );
}
