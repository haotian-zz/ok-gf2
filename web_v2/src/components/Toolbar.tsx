/** 任务列表底部工具栏：全选/折叠/预设 + 暂停 + 开始/停止（沿用 MXU Toolbar）。 */
import clsx from 'clsx';
import {
  CheckSquare,
  ChevronsDownUp,
  ChevronsUpDown,
  Loader2,
  Pause,
  Play,
  Sparkles,
  Square,
  StopCircle,
} from 'lucide-react';
import { currentWorkflow, fieldOf, useStore, workflowEntries, workflowTask } from '@/store';

export function Toolbar() {
  const catalog = useStore((s) => s.catalog);
  const tasks = useStore((s) => s.tasks);
  const status = useStore((s) => s.status);
  const busy = useStore((s) => s.busy);
  const prefs = useStore((s) => s.prefs);
  const expanded = prefs.expanded;
  const showPresets = prefs.showPresetPanel;
  const setPrefs = useStore((s) => s.setPrefs);
  const setAllExpanded = useStore((s) => s.setAllExpanded);
  const setAllEnabled = useStore((s) => s.setAllEnabled);
  const startTask = useStore((s) => s.startTask);
  const stop = useStore((s) => s.stop);
  const togglePause = useStore((s) => s.togglePause);

  const wf = currentWorkflow({ catalog, prefs });
  const daily = wf ? workflowTask({ tasks }, wf) : undefined;
  const entries = wf ? workflowEntries(wf) : [];
  const hasToggles = entries.length > 0;
  const hasPresets = (wf?.presets?.length ?? 0) > 0;
  const startLabel = wf?.start_label ?? (wf ? `开始${wf.label}` : '开始');
  const allEnabled = entries.length > 0 && entries.every((e) => !!fieldOf(daily, e.enable_key!)?.value);
  const anyExpanded = expanded.length > 0;
  const running = !!status.running && !!status.current_task;
  const paused = !!status.paused;
  const starting = !!status.starting;

  const handleStartStop = () => {
    if (running) void stop();
    else if (daily) void startTask(daily.name);
  };

  const toolBtn =
    'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:text-text-muted disabled:cursor-not-allowed disabled:hover:bg-transparent';

  return (
    <div className="flex items-center justify-between px-3 py-2 bg-bg-secondary border-t border-border">
      <div className="flex items-center gap-1">
        {hasToggles && (
          <button
            type="button"
            onClick={() => setAllEnabled(!allEnabled)}
            disabled={!daily || running}
            className={toolBtn}
            title={allEnabled ? '取消全选' : `全选${wf?.label ?? ''}项`}
          >
            {allEnabled ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
            <span className="hidden sm:inline">{allEnabled ? '取消全选' : '全选'}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => setAllExpanded(!anyExpanded)}
          className={toolBtn}
          title={anyExpanded ? '全部折叠' : '全部展开'}
        >
          {anyExpanded ? <ChevronsDownUp className="w-4 h-4" /> : <ChevronsUpDown className="w-4 h-4" />}
          <span className="hidden sm:inline">{anyExpanded ? '折叠' : '展开'}</span>
        </button>
        {hasPresets && (
        <button
          type="button"
          onClick={() => setPrefs({ showPresetPanel: !showPresets })}
          className={clsx(
            'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm transition-colors',
            showPresets ? 'bg-accent/10 text-accent' : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary',
          )}
          title="一键预设"
        >
          <Sparkles className="w-4 h-4" />
          <span className="hidden sm:inline">预设</span>
        </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        {running && (
          <button
            type="button"
            onClick={() => togglePause()}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              paused ? 'bg-warning text-white hover:bg-warning/90' : 'bg-bg-tertiary text-text-secondary hover:bg-bg-hover',
            )}
            title={paused ? '继续执行' : '暂停执行'}
          >
            {paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
            <span>{paused ? '继续' : '暂停'}</span>
          </button>
        )}
        {(running || wf?.task) && (
        <button
          type="button"
          onClick={handleStartStop}
          disabled={busy || (!running && (!daily || starting))}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            running
              ? 'bg-error hover:bg-error/90 text-white'
              : starting
                ? 'bg-success text-white'
                : !daily
                  ? 'bg-bg-active text-text-tertiary cursor-not-allowed'
                  : 'bg-accent hover:bg-accent-hover text-white',
          )}
          title={running ? `停止「${status.current_task}」` : daily ? `开始「${daily.name}」` : `「${wf?.task}」没有注册`}
        >
          {busy || starting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : running ? (
            <StopCircle className="w-4 h-4" />
          ) : (
            <Play className="w-4 h-4" />
          )}
          <span>{running ? '停止' : starting ? '正在启动…' : startLabel}</span>
        </button>
        )}
      </div>
    </div>
  );
}
