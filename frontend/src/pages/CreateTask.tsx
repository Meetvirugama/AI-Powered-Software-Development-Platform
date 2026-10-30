import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, PenTool, GitPullRequest } from 'lucide-react';
import { CreateTaskForm } from '../components/tasks/CreateTaskForm';
import { ImportIssueForm } from '../components/tasks/ImportIssueForm';
import { cn } from '../lib/utils';

export function CreateTask() {
  const [activeTab, setActiveTab] = useState<'manual' | 'github'>('manual');

  return (
    <div className="flex flex-col h-full space-y-6 max-w-5xl mx-auto w-full">
      {/* Top Navigation & Breadcrumbs */}
      <div>
        <Link
          to="/app/tasks"
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors mb-2"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          <span>Back to Tasks</span>
        </Link>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">New Task Intake</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Define structured requirements, architectural assumptions, and constraints or import an existing GitHub Issue.
        </p>
      </div>

      {/* Tabs Selector */}
      <div className="flex items-center gap-2 border-b border-border pb-px">
        <button
          type="button"
          onClick={() => setActiveTab('manual')}
          className={cn(
            'inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors focus:outline-none',
            activeTab === 'manual'
              ? 'border-primary text-primary font-semibold'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
          )}
        >
          <PenTool className="h-4 w-4" />
          <span>Manual Task Creation</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('github')}
          className={cn(
            'inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors focus:outline-none',
            activeTab === 'github'
              ? 'border-primary text-primary font-semibold'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
          )}
        >
          <GitPullRequest className="h-4 w-4" />
          <span>Import from GitHub Issue</span>
        </button>
      </div>

      {/* Tab Content */}
      <div className="pt-2">
        {activeTab === 'manual' ? <CreateTaskForm /> : <ImportIssueForm />}
      </div>
    </div>
  );
}
