import { useState, useMemo } from 'react';
import {
  Folder,
  FolderOpen,
  FileText,
  FileCode,
  File,
  ChevronRight,
  ChevronDown,
  Search,
  X,
} from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';
import type { RepositoryFile } from '../../types/api';

export interface FileTreeProps {
  files: RepositoryFile[];
  isLoading: boolean;
  isError: boolean;
  selectedFile: RepositoryFile | null;
  onSelectFile: (file: RepositoryFile) => void;
  className?: string;
  totalFiles?: number;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  onLoadMore?: () => void;
}

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  file?: RepositoryFile;
  children: TreeNode[];
}

function getFileIcon(filename: string) {
  if (filename.endsWith('.md')) {
    return <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
  }
  if (filename.match(/\.(js|jsx|ts|tsx)$/)) {
    return <FileCode className="h-3.5 w-3.5 text-blue-400 shrink-0" />;
  }
  if (filename.match(/\.(py)$/)) {
    return <FileCode className="h-3.5 w-3.5 text-amber-400 shrink-0" />;
  }
  if (filename.match(/\.(json|yaml|yml|toml)$/)) {
    return <FileCode className="h-3.5 w-3.5 text-emerald-400 shrink-0" />;
  }
  return <File className="h-3.5 w-3.5 text-muted-foreground shrink-0" />;
}

export function FileTree({
  files,
  isLoading,
  isError,
  selectedFile,
  onSelectFile,
  className,
  totalFiles,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: FileTreeProps) {
  const [filter, setFilter] = useState('');
  const [collapsedDirs, setCollapsedDirs] = useState<Record<string, boolean>>({});

  function toggleDir(dirPath: string) {
    setCollapsedDirs((prev) => ({
      ...prev,
      [dirPath]: !prev[dirPath],
    }));
  }

  // Filter files by search query
  const filteredFiles = useMemo(() => {
    if (!filter.trim()) return files;
    const q = filter.toLowerCase();
    return files.filter((f) => f.path.toLowerCase().includes(q));
  }, [files, filter]);

  // Build recursive tree from arbitrary depth paths
  const treeData = useMemo(() => {
    const rootNodes: TreeNode[] = [];
    const dirMap = new Map<string, TreeNode>();

    // Sort paths alphabetically so children attach in order
    const sorted = [...filteredFiles].sort((a, b) => a.path.localeCompare(b.path));

    for (const item of sorted) {
      const isExplicitDir = item.path.endsWith('/');
      const cleanPath = isExplicitDir ? item.path.slice(0, -1) : item.path;
      const parts = cleanPath.split('/').filter(Boolean);

      let currentPath = '';
      let parentNode: TreeNode | null = null;

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        currentPath = currentPath ? `${currentPath}/${part}` : part;
        const isLeaf = i === parts.length - 1;

        if (isLeaf && !isExplicitDir) {
          // File node
          const fileNode: TreeNode = {
            name: part,
            path: item.path,
            isDir: false,
            file: item,
            children: [],
          };
          if (parentNode) {
            parentNode.children.push(fileNode);
          } else {
            rootNodes.push(fileNode);
          }
        } else {
          // Directory node
          let dirNode = dirMap.get(currentPath);
          if (!dirNode) {
            dirNode = {
              name: part,
              path: currentPath,
              isDir: true,
              children: [],
            };
            dirMap.set(currentPath, dirNode);
            if (parentNode) {
              parentNode.children.push(dirNode);
            } else {
              rootNodes.push(dirNode);
            }
          }
          parentNode = dirNode;
        }
      }
    }

    // Sort helper: directories first, then alphabetical
    function sortTree(nodes: TreeNode[]) {
      nodes.sort((a, b) => {
        if (a.isDir && !b.isDir) return -1;
        if (!a.isDir && b.isDir) return 1;
        return a.name.localeCompare(b.name);
      });
      for (const node of nodes) {
        if (node.isDir) {
          sortTree(node.children);
        }
      }
    }

    sortTree(rootNodes);
    return rootNodes;
  }, [filteredFiles]);

  const isSearching = Boolean(filter.trim());

  function renderNode(node: TreeNode, depth: number = 0) {
    if (node.isDir) {
      // If user is searching, keep folders expanded by default so results are visible
      const isCollapsed = isSearching ? false : Boolean(collapsedDirs[node.path]);

      return (
        <div key={node.path} className="flex flex-col">
          <button
            type="button"
            onClick={() => toggleDir(node.path)}
            style={{ paddingLeft: `${depth * 12 + 6}px` }}
            className="flex items-center gap-1.5 w-full py-1 pr-1.5 hover:bg-accent/60 rounded text-foreground font-medium transition-colors text-left group"
          >
            {isCollapsed ? (
              <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
            ) : (
              <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
            )}
            {isCollapsed ? (
              <Folder className="h-3.5 w-3.5 text-amber-500 fill-amber-500/20 shrink-0" />
            ) : (
              <FolderOpen className="h-3.5 w-3.5 text-amber-500 fill-amber-500/20 shrink-0" />
            )}
            <span className="truncate flex-1 text-xs">{node.name}</span>
            <span className="text-[10px] text-muted-foreground/60 font-mono opacity-0 group-hover:opacity-100 transition-opacity">
              {node.children.length}
            </span>
          </button>

          {!isCollapsed && node.children.length > 0 && (
            <div className="flex flex-col">
              {node.children.map((child) => renderNode(child, depth + 1))}
            </div>
          )}
        </div>
      );
    }

    const isSelected = selectedFile?.id === node.file?.id || selectedFile?.path === node.path;

    return (
      <button
        key={node.path}
        type="button"
        onClick={() => node.file && onSelectFile(node.file)}
        style={{ paddingLeft: `${depth * 12 + 18}px` }}
        className={cn(
          'flex w-full items-center gap-1.5 py-1 pr-1.5 rounded text-left transition-colors text-xs font-mono',
          isSelected
            ? 'bg-primary/15 text-primary font-medium border-l-2 border-primary'
            : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
        )}
      >
        {getFileIcon(node.name)}
        <span className="truncate flex-1" title={node.path}>
          {node.name}
        </span>
      </button>
    );
  }

  return (
    <div className={cn('flex-1 min-h-0 flex flex-col', className)}>
      {/* Search files header */}
      <div className="p-2 border-b border-border/60 bg-background/50 shrink-0">
        <div className="relative flex items-center">
          <Search className="h-3 w-3 absolute left-2.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter files…"
            className="w-full pl-7 pr-7 py-1 text-xs rounded-md bg-muted/20 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors font-mono"
          />
          {filter && (
            <button
              onClick={() => setFilter('')}
              className="absolute right-2 text-muted-foreground hover:text-foreground"
              aria-label="Clear file filter"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Tree list */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2 text-xs select-none space-y-0.5">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <LoadingSpinner size="sm" label="Loading tree…" />
          </div>
        ) : isError ? (
          <p className="text-xs text-destructive p-2">Failed to load files.</p>
        ) : treeData.length === 0 ? (
          <p className="text-xs text-muted-foreground italic p-2 text-center">
            {filter ? `No files matching "${filter}"` : 'No files indexed yet.'}
          </p>
        ) : (
          treeData.map((node) => renderNode(node, 0))
        )}
      </div>

      {/* File count and Load More footer (F-02) */}
      {!isLoading && !isError && files.length > 0 && (
        <div className="p-2 border-t border-border/60 bg-background/50 shrink-0 flex flex-col gap-1.5 text-[11px] text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>
              Files: <strong className="text-foreground">{files.length}</strong>
              {totalFiles !== undefined && totalFiles > files.length && (
                <span> / {totalFiles}</span>
              )}
            </span>
            {totalFiles !== undefined && totalFiles > files.length ? (
              <span className="text-[10px] bg-amber-500/10 text-amber-500 px-1.5 py-0.5 rounded font-medium border border-amber-500/20">
                {totalFiles - files.length} more
              </span>
            ) : (
              <span className="text-[10px] text-muted-foreground/60">All loaded</span>
            )}
          </div>
          {hasMore && onLoadMore && (
            <button
              onClick={onLoadMore}
              disabled={isLoadingMore}
              className="w-full py-1 px-2 text-xs rounded bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
            >
              {isLoadingMore ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span>Loading files...</span>
                </>
              ) : (
                <span>Load more files (+500)</span>
              )}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
