import { type ReactNode } from 'react';
import { cn } from '../../lib/utils';

export interface StudioWorkspaceProps {
  activeMobileTab: 'source' | 'results';
  sourcePanel: ReactNode;
  resultsPanel: ReactNode;
  className?: string;
}

export function StudioWorkspace({
  activeMobileTab,
  sourcePanel,
  resultsPanel,
  className,
}: StudioWorkspaceProps) {
  return (
    <div className={cn('flex-1 min-h-0 flex flex-col lg:flex-row overflow-hidden', className)}>
      {/* Left Column: Code / Source Viewer */}
      <div
        className={cn(
          'flex-1 min-h-0 min-w-0 border-r border-border bg-background',
          activeMobileTab === 'results' ? 'hidden lg:flex lg:flex-col' : 'flex flex-col'
        )}
      >
        {sourcePanel}
      </div>

      {/* Right Column: AI Results / Findings Panel */}
      <div
        className={cn(
          'w-full lg:w-[460px] xl:w-[520px] 2xl:w-[580px] flex-shrink-0 flex flex-col min-h-0 bg-card overflow-hidden',
          activeMobileTab === 'source' ? 'hidden lg:flex lg:flex-col' : 'flex flex-col'
        )}
      >
        {resultsPanel}
      </div>
    </div>
  );
}

export default StudioWorkspace;

