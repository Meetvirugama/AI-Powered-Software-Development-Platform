import { useState, useMemo, useEffect, useRef } from 'react';
import { Search, FileCode, Check, X, AlertCircle } from 'lucide-react';
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
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isDebouncing = searchInput !== debouncedSearch;

  useEffect(() => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedSearch(searchInput);
    }, 250);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [searchInput]);

  const filteredFiles = useMemo(() => {
    if (!debouncedSearch.trim()) {
      return files.slice(0, 50);
    }
    const q = debouncedSearch.toLowerCase();
    return files
      .filter((f) => f.path.toLowerCase().includes(q) || (f.language && f.language.toLowerCase().includes(q)))
      .slice(0, 50);
  }, [files, debouncedSearch]);

  const totalLoaded = files.length;
  const isSelectedInList = selectedFile && filteredFiles.some((f) => f.id === selectedFile.id || f.path === selectedFile.path);

  return (
    <div className={cn('flex flex-col bg-card border border-border rounded-lg overflow-hidden', className)}>
      {/* Search Input */}
      <div className="relative p-2 border-b border-border bg-muted/20">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={placeholder}
          className="w-full pl-7 pr-7 py-1.5 text-xs bg-background border border-border rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        {searchInput && (
          <button
            onClick={() => {
              setSearchInput('');
              setDebouncedSearch('');
            }}
            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Selected File Notice when filtered out */}
      {selectedFile && !isSelectedInList && (
        <div className="px-3 py-1.5 bg-primary/5 border-b border-border flex items-center justify-between text-xs text-primary">
          <div className="flex items-center gap-1.5 min-w-0">
            <Check className="h-3 w-3 shrink-0" />
            <span className="truncate">Selected: {selectedFile.path}</span>
          </div>
          <span className="text-[10px] text-muted-foreground ml-2 shrink-0">(Preserved)</span>
        </div>
      )}

      {/* File List */}
      <div className="overflow-y-auto max-h-64 p-1 space-y-0.5">
        {isLoading || isDebouncing ? (
          <div className="p-4 text-center">
            <LoadingSpinner size="sm" label="Searching repository files..." />
          </div>
        ) : filteredFiles.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground space-y-1">
            <AlertCircle className="h-4 w-4 mx-auto text-muted-foreground/60 mb-1" />
            <p className="font-medium">No matching files found</p>
            <p className="text-[11px] text-muted-foreground/80">
              No files matching &ldquo;{debouncedSearch}&rdquo; in {totalLoaded} loaded files.
            </p>
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
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-muted text-muted-foreground">
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

      {/* Footer / Scope Disclaimer */}
      <div className="px-3 py-1.5 border-t border-border/60 bg-muted/10 text-[10px] text-muted-foreground flex items-center justify-between">
        <span>Showing {filteredFiles.length} of {totalLoaded} files</span>
        <span className="text-muted-foreground/70">Loaded repository scope</span>
      </div>
    </div>
  );
}

export default TargetFilePicker;
