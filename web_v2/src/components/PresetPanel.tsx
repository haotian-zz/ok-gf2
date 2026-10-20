/** 一键预设面板（沿用 MXU PresetSelector 的卡片样式）。 */
import { Loader2, Sparkles, X } from 'lucide-react';
import { useState } from 'react';
import { dailyEntries, useStore } from '@/store';

export function PresetPanel() {
  const catalog = useStore((s) => s.catalog);
  const applyPreset = useStore((s) => s.applyPreset);
  const setPrefs = useStore((s) => s.setPrefs);
  const status = useStore((s) => s.status);
  const [applying, setApplying] = useState<string | null>(null);
  if (!catalog) return null;
  const total = dailyEntries(catalog).length;
  const running = !!status.running && !!status.current_task;

  return (
    <div className="border-t border-border bg-bg-primary">
      <div className="flex items-center justify-between px-3 pt-2">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">一键预设</span>
        <button
          type="button"
          onClick={() => setPrefs({ showPresetPanel: false })}
          className="p-1 rounded-md hover:bg-bg-hover text-text-muted"
          title="收起"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-3">
        {catalog.presets.map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={running || applying !== null}
            onClick={async () => {
              setApplying(p.id);
              try {
                await applyPreset(p.id);
              } finally {
                setApplying(null);
              }
            }}
            className="w-full text-left p-3 rounded-lg border border-border bg-bg-secondary hover:bg-bg-hover hover:border-accent transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <div className="flex items-center gap-2 mb-1">
              {applying === p.id ? (
                <Loader2 className="w-4 h-4 text-accent animate-spin flex-shrink-0" />
              ) : (
                <Sparkles className="w-4 h-4 text-accent flex-shrink-0" />
              )}
              <span className="text-sm font-medium text-text-primary truncate">{p.label}</span>
              <span className="text-xs text-text-muted ml-auto flex-shrink-0">
                {p.entries.length}/{total} 项
              </span>
            </div>
            {p.desc && <div className="text-xs text-text-secondary line-clamp-2">{p.desc}</div>}
          </button>
        ))}
      </div>
    </div>
  );
}
