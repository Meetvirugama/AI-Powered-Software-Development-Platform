import { useState, useMemo } from 'react';
import { Search, FileCode, Check, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { RepositoryFile } from '../../types/api';
import { LoadingSpinner } from '../shared/LoadingSpinner';

interface TargetFilePickerProps {
  files: RepositoryFile[];
  isLoading?: boolean;
  selectedFile?: RepositoryFile | null;
  onSelectFile: (file: RepositoryFile) => void;
  className?: string;
  placeholder?: string;
}

export function TargetFilePicker({
  files,
  isLoading,
  selectedFile,
  onSelectFile,
  className,
  placeholder = 'Search repository files (e.g. auth.py, index.ts)...',
}: TargetFilePickerProps) {
  const [search, setSearch] = useState('');

  const filteredFiles = useMemo(() => {
    if (!search.trim()) {
      return files.slice(0, 50); // Show top files initially
    }
    const q = search.toLowerCase();
    return files
      .filter((f) => f.path.toLowerCase().includes(q) || (f.language && f.language.toLowerCase().includes(q)))
      .slice(0, 50);
  }, [files, search]);

  return (
    <div className={cn('flex flex-col bg-card border border-border rounded-lg overflow-hidden', className)}>
      {/* Search Input */}
      <div className="relative p-2 border-b border-border bg-muted/20">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={placeholder}
          className="w-full pl-7 pr-7 py-1.5 text-xs bg-background border border-border rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* File List */}
      <div className="overflow-y-auto max-h-64 p-1 space-y-0.5">
        {isLoading ? (
          <div className="p-4 text-center">
            <LoadingSpinner size="sm" label="Loading repository files..." />
          </div>
        ) : filteredFiles.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            No files matching &ldquo;{search}&rdquo;
          </div>
        ) : (
          filteredFiles.map((f) => {
            const isSelected = selectedFile?.id === f.id || selectedFile?.path === f.path;
            const segments = f.path.split('/');
            const fileName = segments[segments.length - 1];
            const dirPath = segments.slice(0, -1).join('/');

            return (
              <button
                key={f.id}
                onClick={() => onSelectFile(f)}
                className={cn(
                  'w-full text-left px-2.5 py-1.5 rounded-md text-xs flex items-center justify-between gap-2 transition-colors',
                  isSelected
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileCode className={cn('h-3.5 w-3.5 shrink-0', isSelected ? 'text-primary' : 'text-muted-foreground')} />
                  <div className="min-w-0 truncate">
                    <span className="text-foreground">{fileName}</span>
                    {dirPath && <span className="text-[11px] text-muted-foreground/70 ml-1.5">({dirPath})</span>}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {f.language && (
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-muted text-muted-foreground">
                      {f.language}
                    </span>
                  )}
                  {isSelected && <Check className="h-3.5 w-3.5 text-primary" />}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
