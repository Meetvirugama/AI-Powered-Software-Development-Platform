import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  FolderGit2,
  MessageSquare,
  Sparkles,
  ShieldAlert,
  FlaskConical,
  FileCheck,
  ListTodo,
  Search,
  FileCode,
  X,
  CornerDownLeft,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useRepositoryFiles } from '../../hooks/useRepositories';

interface CommandPaletteProps {
  repoId: string;
  isOpen: boolean;
  onClose: () => void;
}

interface PaletteItem {
  id: string;
  type: 'studio' | 'file';
  title: string;
  subtitle?: string;
  icon: typeof FolderGit2;
  action: () => void;
}

function CommandPaletteModal({ repoId, onClose }: { repoId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const { data: filesData } = useRepositoryFiles(repoId, 1, 100);
  const files = useMemo(() => filesData?.items ?? [], [filesData]);

  // Focus search input on mount
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 40);
    return () => clearTimeout(timer);
  }, []);

  // Determine current studio path prefix
  const currentStudioBase = useMemo(() => {
    if (location.pathname.includes('/explain')) return `/app/repositories/${repoId}/explain`;
    if (location.pathname.includes('/bugs')) return `/app/repositories/${repoId}/bugs`;
    if (location.pathname.includes('/tests')) return `/app/repositories/${repoId}/tests`;
    if (location.pathname.includes('/review')) return `/app/repositories/${repoId}/review`;
    if (location.pathname.includes('/tasks')) return `/app/repositories/${repoId}/tasks`;
    if (location.pathname.includes('/chat')) return `/app/repositories/${repoId}/chat`;
    return `/app/repositories/${repoId}/explain`;
  }, [location.pathname, repoId]);

  const studioItems: PaletteItem[] = useMemo(
    () => [
      {
        id: 'studio-explorer',
        type: 'studio',
        title: 'Explorer',
        subtitle: 'Browse repository file tree and symbols',
        icon: FolderGit2,
        action: () => {
          navigate(`/app/repositories/${repoId}`);
          onClose();
        },
      },
      {
        id: 'studio-chat',
        type: 'studio',
        title: 'Chat Studio',
        subtitle: 'Ask questions grounded in codebase RAG context',
        icon: MessageSquare,
        action: () => {
          navigate(`/app/repositories/${repoId}/chat`);
          onClose();
        },
      },
      {
        id: 'studio-explain',
        type: 'studio',
        title: 'Explain Studio',
        subtitle: 'Deep code walkthrough and grounded citations',
        icon: Sparkles,
        action: () => {
          navigate(`/app/repositories/${repoId}/explain`);
          onClose();
        },
      },
      {
        id: 'studio-bugs',
        type: 'studio',
        title: 'Bug Hunter',
        subtitle: 'Triage vulnerabilities and inspect patch proposals',
        icon: ShieldAlert,
        action: () => {
          navigate(`/app/repositories/${repoId}/bugs`);
          onClose();
        },
      },
      {
        id: 'studio-tests',
        type: 'studio',
        title: 'Test Studio',
        subtitle: 'Generate scenario unit tests with path safety checks',
        icon: FlaskConical,
        action: () => {
          navigate(`/app/repositories/${repoId}/tests`);
          onClose();
        },
      },
      {
        id: 'studio-review',
        type: 'studio',
        title: 'Code Review Studio',
        subtitle: 'Inspect PR diffs, risk scorecards, and findings',
        icon: FileCheck,
        action: () => {
          navigate(`/app/repositories/${repoId}/review`);
          onClose();
        },
      },
      {
        id: 'studio-tasks',
        type: 'studio',
        title: 'Agent Tasks Studio',
        subtitle: 'Import GitHub issues, generate execution plans, and approve runs',
        icon: ListTodo,
        action: () => {
          navigate(`/app/repositories/${repoId}/tasks`);
          onClose();
        },
      },
    ],
    [repoId, navigate, onClose]
  );

  const fileItems: PaletteItem[] = useMemo(() => {
    return files.map((file) => ({
      id: `file-${file.id}`,
      type: 'file',
      title: file.path,
      subtitle: `${file.language} · ${file.size_bytes ? `${Math.round(file.size_bytes / 1024)} KB` : 'file'}`,
      icon: FileCode,
      action: () => {
        navigate(`${currentStudioBase}?file=${encodeURIComponent(file.path)}`);
        onClose();
      },
    }));
  }, [files, currentStudioBase, navigate, onClose]);

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return [...studioItems, ...fileItems.slice(0, 15)];
    }
    const matchedStudios = studioItems.filter(
      (s) => s.title.toLowerCase().includes(q) || s.subtitle?.toLowerCase().includes(q)
    );
    const matchedFiles = fileItems.filter((f) => f.title.toLowerCase().includes(q));
    return [...matchedStudios, ...matchedFiles.slice(0, 20)];
  }, [query, studioItems, fileItems]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredItems.length));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % Math.max(1, filteredItems.length));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredItems[selectedIndex]) {
          filteredItems[selectedIndex].action();
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    },
    [filteredItems, selectedIndex, onClose]
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Repository Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 sm:pt-24 px-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl rounded-xl border border-border/80 bg-card shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/60 bg-muted/20">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="Type a studio name, or file path to jump..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-hidden"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="p-1 rounded text-muted-foreground hover:text-foreground"
              aria-label="Clear query"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground bg-accent rounded border border-border">
            ESC
          </kbd>
        </div>

        {/* Results list */}
        <div ref={listRef} className="overflow-y-auto p-2 divide-y divide-border/20 max-h-[420px]">
          {filteredItems.length === 0 ? (
            <div className="py-10 text-center text-xs text-muted-foreground">
              No studios or files matching &ldquo;{query}&rdquo;
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const Icon = item.icon;
              const isSelected = idx === selectedIndex;
              return (
                <button
                  key={item.id}
                  onClick={item.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-xs transition-colors',
                    isSelected
                      ? 'bg-primary/10 text-primary border border-primary/30'
                      : 'hover:bg-accent/50 text-foreground border border-transparent'
                  )}
                >
                  <div
                    className={cn(
                      'p-1.5 rounded-md shrink-0',
                      item.type === 'studio' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
                    )}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{item.title}</div>
                    {item.subtitle && (
                      <div className="text-[11px] text-muted-foreground truncate">{item.subtitle}</div>
                    )}
                  </div>
                  {isSelected && (
                    <div className="flex items-center gap-1 text-[11px] text-primary shrink-0">
                      <span>Jump</span>
                      <CornerDownLeft className="h-3 w-3" />
                    </div>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2 bg-muted/30 border-t border-border/40 flex items-center justify-between text-[11px] text-muted-foreground">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↑</kbd>{' '}
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↓</kbd> navigate
            </span>
            <span>
              <kbd className="font-mono bg-accent px-1 py-0.5 rounded border border-border">↵</kbd> select
            </span>
          </div>
          <span className="font-mono text-[10px]">Antigravity Command Palette</span>
        </div>
      </div>
    </div>
  );
}

export function CommandPalette({ repoId, isOpen, onClose }: CommandPaletteProps) {
  if (!isOpen) return null;
  return <CommandPaletteModal repoId={repoId} onClose={onClose} />;
}
