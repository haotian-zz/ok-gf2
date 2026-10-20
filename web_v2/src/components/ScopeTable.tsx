/** 设置页「阵容与助战」里的各场景一览：哪些场景和全局不一样，可跳去改或恢复全局。 */
import clsx from 'clsx';
import { ExternalLink, RotateCcw } from 'lucide-react';
import { LINEUP_GROUP, entryOfScope, lineupScopes, resetScopeChanges, scopeState, useStore } from '@/store';

export function ScopeTable() {
  const settings = useStore((s) => s.settings);
  const catalog = useStore((s) => s.catalog);
  const setSettings = useStore((s) => s.setSettings);
  const focusEntry = useStore((s) => s.focusEntry);
  const scopes = lineupScopes(settings);
  if (!scopes.length) return null;

  return (
    <div className="pt-2">
      <div className="text-sm text-text-secondary">各场景单独设置</div>
      <div className="text-xs text-text-muted mt-0.5">在任务页对应板块的「阵容」卡片里改；这里一览哪些场景和全局不一样。</div>
      <table className="w-full mt-2 text-xs border-collapse">
        <thead>
          <tr className="text-text-muted">
            <th className="text-left font-medium px-2 py-1.5 border-b border-border">场景</th>
            <th className="text-left font-medium px-2 py-1.5 border-b border-border">编队</th>
            <th className="text-left font-medium px-2 py-1.5 border-b border-border">借助战</th>
            <th className="border-b border-border" />
          </tr>
        </thead>
        <tbody>
          {scopes.map((scope) => {
            const st = scopeState(settings, scope)!;
            const entry = catalog ? entryOfScope(catalog, scope) : undefined;
            return (
              <tr key={scope} className={clsx(st.overridden && 'bg-accent/5')}>
                <td className={clsx('px-2 py-1.5 border-b border-border/60 text-text-primary', st.overridden && 'border-l-2 border-l-accent')}>{scope}</td>
                <td className={clsx('px-2 py-1.5 border-b border-border/60', st.preset ? 'text-accent font-medium' : 'text-text-muted')}>
                  {st.preset || `沿用（${st.globalPreset || '不切'}）`}
                </td>
                <td className={clsx('px-2 py-1.5 border-b border-border/60', st.support && st.support !== '沿用全局' ? 'text-accent font-medium' : 'text-text-muted')}>
                  {st.support === null ? '—' : st.support === '沿用全局' ? `沿用（${st.globalSupport ? '开' : '关'}）` : st.support}
                </td>
                <td className="px-2 py-1.5 border-b border-border/60 text-right whitespace-nowrap">
                  {entry && (
                    <button
                      type="button"
                      onClick={() => focusEntry(entry.id)}
                      className="inline-flex items-center gap-1 text-text-muted hover:text-accent transition-colors mr-3"
                    >
                      <ExternalLink className="w-3 h-3" />
                      去设置
                    </button>
                  )}
                  {st.overridden && (
                    <button
                      type="button"
                      onClick={() => setSettings(LINEUP_GROUP, resetScopeChanges(settings, scope))}
                      className="inline-flex items-center gap-1 text-text-muted hover:text-accent transition-colors"
                    >
                      <RotateCcw className="w-3 h-3" />
                      恢复全局
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
