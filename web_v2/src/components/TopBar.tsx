/** 顶栏（对应 MXU TabBar）：左边页签，右边主题切换和设置。 */
import clsx from 'clsx';
import { ListTodo, Moon, Settings, Sun } from 'lucide-react';
import { useStore } from '@/store';
import { resolveThemeMode } from '@/themes';
import { StatusIndicator } from './StatusPanel';

export function TopBar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const title = useStore((s) => s.title);
  const themePreference = useStore((s) => s.themePreference);
  const setThemePreference = useStore((s) => s.setThemePreference);
  const status = useStore((s) => s.status);
  const running = !!status.running && !!status.current_task;
  const mode = resolveThemeMode(themePreference);

  return (
    <div className="flex items-center h-10 bg-bg-secondary border-b border-border select-none shrink-0">
      <div className="flex-1 flex items-center h-full overflow-x-auto">
        <button
          type="button"
          onClick={() => setPage('main')}
          className={clsx(
            'flex items-center gap-1.5 h-full px-3 cursor-pointer border-r border-border min-w-[120px] text-sm',
            page === 'main'
              ? 'bg-bg-primary text-accent border-b-2 border-b-accent'
              : 'bg-bg-tertiary text-text-secondary hover:bg-bg-hover border-b-2 border-b-transparent',
          )}
        >
          {running && <span className="w-2 h-2 rounded-full bg-accent task-running-indicator flex-shrink-0" />}
          <ListTodo className="w-4 h-4" />
          <span className="truncate">任务</span>
        </button>
        <div className="px-3">
          <StatusIndicator />
        </div>
      </div>

      <div className="hidden md:block px-4 text-sm font-medium text-text-secondary">{title}</div>

      <div className="flex items-center gap-1 px-2">
        <button
          type="button"
          onClick={() => setThemePreference(mode === 'light' ? 'dark' : 'light')}
          className="p-2 rounded-md hover:bg-bg-hover transition-colors"
          title={mode === 'light' ? '切换到深色' : '切换到浅色'}
        >
          {mode === 'light' ? <Moon className="w-4 h-4 text-text-secondary" /> : <Sun className="w-4 h-4 text-text-secondary" />}
        </button>
        <button
          type="button"
          onClick={() => setPage(page === 'settings' ? 'main' : 'settings')}
          className={clsx('p-2 rounded-md transition-colors', page === 'settings' ? 'bg-accent/10 text-accent' : 'hover:bg-bg-hover text-text-secondary')}
          title="设置"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
