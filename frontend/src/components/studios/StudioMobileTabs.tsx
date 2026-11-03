import { cn } from '../../lib/utils';

export interface StudioMobileTabsProps {
  activeTab: 'source' | 'results';
  onTabChange: (tab: 'source' | 'results') => void;
  className?: string;
}

export function StudioMobileTabs({ activeTab, onTabChange, className }: StudioMobileTabsProps) {
  return (
    <div className={cn('flex lg:hidden items-center p-0.5 rounded-lg bg-muted text-xs font-medium', className)}>
      <button
        onClick={() => onTabChange('source')}
        className={cn(
          'px-2.5 py-1 rounded-md transition-colors',
          activeTab === 'source'
            ? 'bg-background text-foreground shadow-2xs font-semibold'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        Source
      </button>
      <button
        onClick={() => onTabChange('results')}
        className={cn(
          'px-2.5 py-1 rounded-md transition-colors',
          activeTab === 'results'
            ? 'bg-background text-foreground shadow-2xs font-semibold'
            : 'text-muted-foreground hover:text-foreground'
        )}
      >
        Results
      </button>
    </div>
  );
}

export default StudioMobileTabs;

