import { useState, useMemo, useEffect, useRef } from 'react';
import {
  Search,
  FileCode,
  FileText,
  Image as ImageIcon,
  Film,
  Archive,
  FileJson,
  Settings,
  Check,
  X,
  AlertCircle,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { resolveFileType, type FileCategory } from '../../lib/fileLanguage';
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

function getCategoryIcon(category: FileCategory, isSelected: boolean) {
  const baseClass = cn('h-3.5 w-3.5 shrink-0', isSelected ? 'text-primary' : 'text-muted-foreground');
  switch (category) {
    case 'image':
      return <ImageIcon className={baseClass} />;
    case 'media':
      return <Film className={baseClass} />;
    case 'archive':
      return <Archive className={baseClass} />;
    case 'document':
    case 'documentation':
    case 'text':
      return <FileText className={baseClass} />;
    case 'data':
      return <FileJson className={baseClass} />;
    case 'config':
      return <Settings className={baseClass} />;
    default:
      return <FileCode className={baseClass} />;
  }
}

export function TargetFilePicker({
  files,
  isLoading,
  selectedFile,
  onSelectFile,
  className,
  placeholder = 'Search repository files (name, path, or language)…',
}: TargetFilePickerProps) {
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [focusedIndex, setFocusedIndex] = useState(0);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isDebouncing = searchInput !== debouncedSearch;

  useEffect(() => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedSearch(searchInput);
      setFocusedIndex(0);
    }, 200);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [searchInput]);

  const enrichedFiles = useMemo(
    () =>
      files.map((file) => ({
        file,
        resolved: resolveFileType(file.path, file.language),
      })),
    [files]
  );

  const filteredFiles = useMemo(() => {
    if (!debouncedSearch.trim()) {
      return enrichedFiles.slice(0, 50);
    }
    const q = debouncedSearch.trim().toLowerCase();
    return enrichedFiles
      .filter(({ file, resolved }) => {
        return (
          file.path.toLowerCase().includes(q) ||
          resolved.label.toLowerCase().includes(q) ||
          resolved.id.toLowerCase().includes(q) ||
          resolved.extension.toLowerCase().includes(q) ||
          resolved.category.toLowerCase().includes(q)
        );
      })
      .slice(0, 50);
  }, [enrichedFiles, debouncedSearch]);

  const totalLoaded = files.length;
  const isSelectedInList =
    selectedFile &&
    filteredFiles.some(({ file }) => file.id === selectedFile.id || file.path === selectedFile.path);

  const safeFocusedIndex =
    filteredFiles.length === 0 ? 0 : Math.min(focusedIndex, filteredFiles.length - 1);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (filteredFiles.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev + 1) % filteredFiles.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev - 1 + filteredFiles.length) % filteredFiles.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = filteredFiles[safeFocusedIndex];
      if (target) onSelectFile(target.file);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Target file picker"
      className={cn(
        'flex flex-col bg-card text-card-foreground border border-border rounded-xl shadow-xl overflow-hidden',
        className
      )}
    >
      {/* Search Input */}
      <div className="relative p-2 border-b border-border bg-muted/20">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="Search repository files"
          className="w-full pl-7 pr-7 py-1.5 text-xs bg-background border border-border rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
        />
        {searchInput && (
          <button
            type="button"
            onClick={() => {
              setSearchInput('');
              setDebouncedSearch('');
              setFocusedIndex(0);
            }}
            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Selected File Notice when filtered out */}
      {selectedFile && !isSelectedInList && (
        <div className="px-3 py-1.5 bg-muted/40 border-b border-border flex items-center justify-between text-xs text-foreground">
          <div className="flex items-center gap-1.5 min-w-0">
            <Check className="h-3 w-3 shrink-0" />
            <span className="truncate font-mono text-[11px]">Selected: {selectedFile.path}</span>
          </div>
          <span className="text-[10px] text-muted-foreground ml-2 shrink-0">(Preserved)</span>
        </div>
      )}

      {/* File List */}
      <div className="overflow-y-auto max-h-64 p-1.5 space-y-0.5">
        {isLoading || isDebouncing ? (
          <div className="p-4 text-center">
            <LoadingSpinner size="sm" label="Searching repository files..." />
          </div>
        ) : filteredFiles.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground space-y-1">
            <AlertCircle className="h-4 w-4 mx-auto text-muted-foreground/60 mb-1" />
            <p className="font-medium text-foreground">No matching files found</p>
            <p className="text-[11px] text-muted-foreground">
              No files matching &ldquo;{debouncedSearch}&rdquo; in {totalLoaded} loaded files.
            </p>
          </div>
        ) : (
          filteredFiles.map(({ file: f, resolved }, idx) => {
            const isSelected = selectedFile?.id === f.id || selectedFile?.path === f.path;
            const isFocused = idx === safeFocusedIndex;
            const segments = f.path.split('/');
            const fileName = segments[segments.length - 1];
            const dirPath = segments.slice(0, -1).join('/');

            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => onSelectFile(f)}
                onMouseEnter={() => setFocusedIndex(idx)}
                className={cn(
                  'w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center justify-between gap-2 transition-colors cursor-pointer',
                  isSelected
                    ? 'bg-accent text-foreground font-medium'
                    : isFocused
                      ? 'bg-accent/60 text-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {getCategoryIcon(resolved.category, isSelected)}
                  <div className="min-w-0 truncate">
                    <span className="text-foreground">{fileName}</span>
                    {dirPath && <span className="text-[11px] text-muted-foreground ml-1.5">{dirPath}</span>}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <span
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[10px] font-mono border',
                      resolved.isBinaryOrMedia
                        ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20'
                        : 'bg-muted text-muted-foreground border-border/60'
                    )}
                  >
                    {resolved.label}
                  </span>
                  {isSelected && <Check className="h-3.5 w-3.5 text-foreground" />}
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Footer / Scope Disclaimer */}
      <div className="px-3 py-1.5 border-t border-border bg-muted/20 text-[10px] text-muted-foreground flex items-center justify-between">
        <span className="tabular-nums">
          Showing {filteredFiles.length} of {totalLoaded} files
        </span>
        <span className="text-muted-foreground/80">↑↓ navigate · ↵ select</span>
      </div>
    </div>
  );
}

export default TargetFilePicker;
