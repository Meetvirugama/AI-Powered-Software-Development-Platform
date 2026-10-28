import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileCode, Check, Copy, MessageSquare, X } from 'lucide-react';
import { useRepositoryFileContent } from '../../hooks/useRepositories';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import type { RepositoryFile } from '../../types/api';

export interface FilePreviewModalProps {
  repositoryId: string;
  file: RepositoryFile;
  onClose: () => void;
}

export function FilePreviewModal({
  repositoryId,
  file,
  onClose,
}: FilePreviewModalProps) {
  const navigate = useNavigate();
  const { data: fileData, isLoading, isError } = useRepositoryFileContent(repositoryId, file.id);
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!fileData?.content) return;
    try {
      await navigator.clipboard.writeText(fileData.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200"
    >
      <div className="relative flex flex-col w-full max-w-5xl max-h-[90vh] rounded-xl border border-border bg-card shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3 bg-muted/20">
          <div className="flex items-center gap-3 min-w-0">
            <FileCode className="h-5 w-5 text-primary shrink-0" />
            <div className="min-w-0">
              <h3 className="font-mono text-sm font-semibold text-foreground truncate">
                {file.path}
              </h3>
              <p className="text-xs text-muted-foreground">
                {file.line_count} lines · {(file.size_bytes / 1024).toFixed(1)} KB
                {file.language && ` · ${file.language}`}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {fileData?.content && (
              <button
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-mono text-foreground hover:bg-accent transition-colors"
                title="Copy code"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            )}

            <button
              onClick={() => {
                onClose();
                navigate(`/app/repositories/${repositoryId}/chat?file=${encodeURIComponent(file.path)}`);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 text-primary px-3 py-1.5 text-xs font-medium hover:bg-primary hover:text-primary-foreground transition-colors"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>Ask AI About File</span>
            </button>

            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              aria-label="Close preview"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-auto p-5 font-mono text-xs">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <LoadingSpinner size="md" label="Loading code content…" />
              <span className="text-muted-foreground text-xs font-mono">Loading file content…</span>
            </div>
          ) : isError ? (
            <p className="text-destructive py-8 font-sans">
              Could not load file content. Chunks might still be indexing.
            </p>
          ) : (
            <div className="space-y-4">
              {fileData?.symbols && fileData.symbols.length > 0 && (
                <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
                  <span className="font-sans text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Extracted Symbols ({fileData.symbols.length})
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {fileData.symbols.map((sym) => (
                      <span
                        key={sym.id}
                        className="inline-flex items-center gap-1.5 rounded bg-background border border-border px-2 py-1 text-xs text-foreground"
                      >
                        <span className="text-primary font-bold">{sym.kind}</span>
                        <span>{sym.name}</span>
                        <span className="text-muted-foreground text-[10px]">
                          L{sym.start_line}–{sym.end_line}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="rounded-lg border border-border bg-background p-4 overflow-x-auto text-foreground font-mono text-xs leading-relaxed whitespace-pre">
                {fileData?.content ? (
                  fileData.content
                ) : (
                  <span className="text-muted-foreground italic font-sans">
                    Empty file or non-indexed binary content.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
