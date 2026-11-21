/**
 * ReviewPublicationSettings — Module 10 "Publication Permission".
 *
 * The backend only posts review comments to a GitHub PR when the repository's
 * `pr_review_enabled` setting is on. That switch (and the saved minimum
 * confidence / comment limit / changed-lines-only policy that publication now
 * uses) had an API but no UI, so this panel exposes it next to the Publish
 * button.
 */

import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, Wrench } from 'lucide-react';
import { getReviewSettings, updateReviewSettings } from '../../services/analysis';
import { cn } from '../../lib/utils';

interface Settings {
  pr_review_enabled: boolean;
  min_confidence: string;
  max_comments: number;
  changed_lines_only: boolean;
}

export function ReviewPublicationSettings({ repositoryId }: { repositoryId: string }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getReviewSettings(repositoryId)
      .then((s) => {
        if (!cancelled) {
          setSettings({
            pr_review_enabled: s.pr_review_enabled,
            min_confidence: s.min_confidence,
            max_comments: s.max_comments,
            changed_lines_only: s.changed_lines_only,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setMessage({ kind: 'error', text: 'Could not load publication settings.' });
      });
    return () => {
      cancelled = true;
    };
  }, [repositoryId]);

  async function save() {
    if (!settings) return;
    setSaving(true);
    setMessage(null);
    try {
      const saved = await updateReviewSettings(repositoryId, settings);
      setSettings({
        pr_review_enabled: saved.pr_review_enabled,
        min_confidence: saved.min_confidence,
        max_comments: saved.max_comments,
        changed_lines_only: saved.changed_lines_only,
      });
      setMessage({ kind: 'ok', text: 'Saved.' });
    } catch (err: any) {
      setMessage({ kind: 'error', text: err?.message || 'Could not save settings.' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-border/50 bg-muted/10 text-[11px]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-2 py-1.5 text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        <span className="inline-flex items-center gap-1.5">
          <Wrench className="h-3 w-3" />
          Publication settings
          {settings && (
            <span
              className={cn(
                'px-1.5 py-0.5 rounded border font-mono text-[10px]',
                settings.pr_review_enabled
                  ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
                  : 'border-border/60 text-muted-foreground'
              )}
            >
              {settings.pr_review_enabled ? 'Publishing allowed' : 'Publishing off'}
            </span>
          )}
        </span>
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>

      {open && (
        <div className="px-2 pb-2 space-y-2 border-t border-border/40 pt-2">
          {!settings ? (
            <div className="text-muted-foreground">{message?.text ?? 'Loading…'}</div>
          ) : (
            <>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={settings.pr_review_enabled}
                  onChange={(e) => setSettings({ ...settings, pr_review_enabled: e.target.checked })}
                />
                Allow publishing review comments to GitHub pull requests
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={settings.changed_lines_only}
                  onChange={(e) => setSettings({ ...settings, changed_lines_only: e.target.checked })}
                />
                Only comment on lines changed in the PR
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5">
                  Min confidence
                  <select
                    value={settings.min_confidence}
                    onChange={(e) => setSettings({ ...settings, min_confidence: e.target.value })}
                    className="bg-background border border-border/60 rounded px-1 py-0.5"
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  Max comments
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={settings.max_comments}
                    onChange={(e) =>
                      setSettings({
                        ...settings,
                        max_comments: Math.min(50, Math.max(1, Number(e.target.value) || 1)),
                      })
                    }
                    className="w-14 bg-background border border-border/60 rounded px-1 py-0.5"
                  />
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={save}
                  disabled={saving}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                >
                  {saving && <Loader2 className="h-3 w-3 animate-spin" />}
                  Save
                </button>
                {message && (
                  <span className={message.kind === 'ok' ? 'text-emerald-400' : 'text-rose-400'}>{message.text}</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
