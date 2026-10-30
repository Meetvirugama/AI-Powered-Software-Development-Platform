import { useState, useId } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plus,
  Trash2,
  AlertCircle,
  FolderGit2,
  FileCode,
  ShieldAlert,
  HelpCircle,
  ArrowRight,
} from 'lucide-react';
import { useCreateTask } from '../../hooks/useTasks';
import { useRepositories } from '../../hooks/useRepositories';
import type {
  TaskCreateRequest,
  TaskSourceType,
  TaskRequirement,
  TaskRequirementCategory,
  TaskAssumption,
  TaskRiskLevel,
  TaskConstraint,
  TaskConstraintType,
} from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';

const REQUIREMENT_CATEGORIES: TaskRequirementCategory[] = [
  'functional',
  'bug_fix',
  'refactor',
  'security',
  'test',
];

const RISK_LEVELS: TaskRiskLevel[] = ['low', 'medium', 'high'];

const CONSTRAINT_TYPES: TaskConstraintType[] = [
  'protected_file',
  'forbidden_dependency',
  'backward_compatibility',
  'resource_limit',
  'security_policy',
];

export function CreateTaskForm() {
  const navigate = useNavigate();
  const formId = useId();

  // Load repositories for selector
  const { data: repoData } = useRepositories(1, 100);

  // Task creation mutation
  const createTaskMutation = useCreateTask();

  // Basic fields state
  const [repositoryId, setRepositoryId] = useState<string>('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [sourceType, setSourceType] = useState<TaskSourceType>('USER_PROMPT');
  const [issueNumber, setIssueNumber] = useState('');
  const [issueUrl, setIssueUrl] = useState('');
  const [findingId, setFindingId] = useState('');
  const [baseRevision, setBaseRevision] = useState('');

  // Dynamic Requirements (min 1 required)
  const [requirements, setRequirements] = useState<
    Array<{
      id: string;
      description: string;
      category: TaskRequirementCategory;
      targetFilesStr: string;
      acceptanceCriteriaStr: string;
    }>
  >([
    {
      id: 'req-1',
      description: '',
      category: 'functional',
      targetFilesStr: '',
      acceptanceCriteriaStr: '',
    },
  ]);

  // Dynamic Assumptions
  const [assumptions, setAssumptions] = useState<
    Array<{
      id: string;
      description: string;
      unresolved: boolean;
      risk_level: TaskRiskLevel;
    }>
  >([]);

  // Dynamic Constraints
  const [constraints, setConstraints] = useState<
    Array<{
      id: string;
      description: string;
      constraint_type: TaskConstraintType;
      forbiddenFilesStr: string;
      forbiddenPackagesStr: string;
      maxBudgetTokensStr: string;
    }>
  >([]);

  // Client-side validation errors
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  // --------------------------------------------------------------------------
  // Requirement Handlers
  // --------------------------------------------------------------------------
  function addRequirement() {
    const nextIndex = requirements.length + 1;
    setRequirements((prev) => [
      ...prev,
      {
        id: `req-${nextIndex}`,
        description: '',
        category: 'functional',
        targetFilesStr: '',
        acceptanceCriteriaStr: '',
      },
    ]);
  }

  function removeRequirement(index: number) {
    if (requirements.length <= 1) return; // Keep at least one
    setRequirements((prev) => prev.filter((_, i) => i !== index));
  }

  function updateRequirement(
    index: number,
    field: string,
    value: string
  ) {
    setRequirements((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: value };
      return copy;
    });
  }

  // --------------------------------------------------------------------------
  // Assumption Handlers
  // --------------------------------------------------------------------------
  function addAssumption() {
    const nextIndex = assumptions.length + 1;
    setAssumptions((prev) => [
      ...prev,
      {
        id: `asm-${nextIndex}`,
        description: '',
        unresolved: false,
        risk_level: 'low',
      },
    ]);
  }

  function removeAssumption(index: number) {
    setAssumptions((prev) => prev.filter((_, i) => i !== index));
  }

  function updateAssumption(
    index: number,
    field: string,
    value: unknown
  ) {
    setAssumptions((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: value };
      return copy;
    });
  }

  // --------------------------------------------------------------------------
  // Constraint Handlers
  // --------------------------------------------------------------------------
  function addConstraint() {
    const nextIndex = constraints.length + 1;
    setConstraints((prev) => [
      ...prev,
      {
        id: `cst-${nextIndex}`,
        description: '',
        constraint_type: 'protected_file',
        forbiddenFilesStr: '',
        forbiddenPackagesStr: '',
        maxBudgetTokensStr: '',
      },
    ]);
  }

  function removeConstraint(index: number) {
    setConstraints((prev) => prev.filter((_, i) => i !== index));
  }

  function updateConstraint(
    index: number,
    field: string,
    value: string
  ) {
    setConstraints((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: value };
      return copy;
    });
  }

  // --------------------------------------------------------------------------
  // Validation and Submission
  // --------------------------------------------------------------------------
  function validate(): boolean {
    const errors: Record<string, string> = {};

    const trimmedRepo = repositoryId.trim() || (repoData?.items?.[0]?.id ?? '');
    if (!trimmedRepo) {
      errors.repositoryId = 'Please select or enter a repository ID.';
    }

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      errors.title = 'Title must contain non-whitespace characters.';
    } else if (trimmedTitle.length < 3 || trimmedTitle.length > 256) {
      errors.title = 'Title must be between 3 and 256 characters in length.';
    }

    if (!description.trim()) {
      errors.description = 'Task description is required.';
    }

    if (requirements.length === 0) {
      errors.requirements = 'At least one requirement is required.';
    } else {
      const emptyReq = requirements.findIndex((r) => !r.description.trim());
      if (emptyReq !== -1) {
        errors.requirements = `Requirement #${emptyReq + 1} has an empty description.`;
      }
    }

    // Check disjointness between target_files and forbidden_files
    const forbiddenFilesSet = new Set<string>();
    for (const c of constraints) {
      const files = c.forbiddenFilesStr
        .split(',')
        .map((f) => f.trim())
        .filter(Boolean);
      for (const f of files) forbiddenFilesSet.add(f);
    }

    for (const r of requirements) {
      const targetFiles = r.targetFilesStr
        .split(',')
        .map((f) => f.trim())
        .filter(Boolean);
      for (const tf of targetFiles) {
        if (forbiddenFilesSet.has(tf)) {
          errors.disjointness = `Conflict: Target file "${tf}" in requirement "${r.id}" is also listed as a forbidden constraint file.`;
          break;
        }
      }
      if (errors.disjointness) break;
    }

    setClientErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    const chosenRepo = repositoryId.trim() || (repoData?.items?.[0]?.id ?? 'repo-1');

    // Build requirements payload
    const formattedRequirements: TaskRequirement[] = requirements.map((r) => ({
      id: r.id,
      description: r.description.trim(),
      category: r.category,
      target_files: r.targetFilesStr
        .split(',')
        .map((f) => f.trim())
        .filter(Boolean),
      acceptance_criteria: r.acceptanceCriteriaStr
        .split('\n')
        .concat(r.acceptanceCriteriaStr.split(','))
        .map((c) => c.trim())
        .filter(Boolean),
    }));

    // Build assumptions payload
    const formattedAssumptions: TaskAssumption[] = assumptions
      .filter((a) => a.description.trim())
      .map((a) => ({
        id: a.id,
        description: a.description.trim(),
        unresolved: a.unresolved,
        risk_level: a.risk_level,
      }));

    // Build constraints payload
    const formattedConstraints: TaskConstraint[] = constraints
      .filter((c) => c.description.trim() || c.forbiddenFilesStr.trim())
      .map((c) => ({
        id: c.id,
        description: c.description.trim() || `Constraint on ${c.constraint_type}`,
        constraint_type: c.constraint_type,
        forbidden_files: c.forbiddenFilesStr
          .split(',')
          .map((f) => f.trim())
          .filter(Boolean),
        forbidden_packages: c.forbiddenPackagesStr
          .split(',')
          .map((p) => p.trim())
          .filter(Boolean),
        max_budget_tokens: c.maxBudgetTokensStr ? parseInt(c.maxBudgetTokensStr, 10) : undefined,
      }));

    const payload: TaskCreateRequest = {
      repository_id: chosenRepo,
      title: title.trim(),
      description: description.trim(),
      source: {
        type: sourceType,
        issue_number: issueNumber ? parseInt(issueNumber, 10) : undefined,
        issue_url: issueUrl.trim() || undefined,
        finding_id: findingId.trim() || undefined,
        repository_id: chosenRepo,
        base_revision: baseRevision.trim() || undefined,
      },
      requirements: formattedRequirements,
      assumptions: formattedAssumptions.length > 0 ? formattedAssumptions : undefined,
      constraints: formattedConstraints.length > 0 ? formattedConstraints : undefined,
      base_revision: baseRevision.trim() || null,
    };

    try {
      const newTask = await createTaskMutation.mutateAsync(payload);
      navigate(`/app/tasks/${newTask.task_id}`);
    } catch {
      // Error handled by mutation state
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8" noValidate>
      {/* Backend / Mutation Error */}
      {createTaskMutation.isError && (
        <ErrorMessage error={createTaskMutation.error} />
      )}

      {/* Disjointness or general validation error */}
      {clientErrors.disjointness && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive flex items-start gap-2.5">
          <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
          <span>{clientErrors.disjointness}</span>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Section 1: Basic Information                                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4 shadow-xs">
        <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
          <FolderGit2 className="h-4 w-4 text-primary" />
          General Task Information
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Repository Selector */}
          <div>
            <label
              htmlFor={`${formId}-repo`}
              className="block text-xs font-medium text-foreground mb-1"
            >
              Repository <span className="text-destructive">*</span>
            </label>
            {repoData?.items && repoData.items.length > 0 ? (
              <select
                id={`${formId}-repo`}
                value={repositoryId || repoData.items[0].id}
                onChange={(e) => setRepositoryId(e.target.value)}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {repoData.items.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.full_name || repo.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`${formId}-repo`}
                type="text"
                placeholder="e.g. repo-1"
                value={repositoryId}
                onChange={(e) => setRepositoryId(e.target.value)}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            )}
            {clientErrors.repositoryId && (
              <p className="mt-1 text-xs text-destructive">{clientErrors.repositoryId}</p>
            )}
          </div>

          {/* Source Type Selector */}
          <div>
            <label
              htmlFor={`${formId}-source`}
              className="block text-xs font-medium text-foreground mb-1"
            >
              Intake Source Type
            </label>
            <select
              id={`${formId}-source`}
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as TaskSourceType)}
              className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="USER_PROMPT">User Prompt</option>
              <option value="GITHUB_ISSUE">GitHub Issue</option>
              <option value="BUG_FINDING">Bug Scanner Finding</option>
              <option value="REVIEW_FINDING">Code Review Finding</option>
            </select>
          </div>
        </div>

        {/* Source-specific extra fields */}
        {sourceType === 'GITHUB_ISSUE' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-border/50">
            <div>
              <label
                htmlFor={`${formId}-issue-num`}
                className="block text-xs font-medium text-foreground mb-1"
              >
                GitHub Issue Number
              </label>
              <input
                id={`${formId}-issue-num`}
                type="number"
                placeholder="e.g. 42"
                value={issueNumber}
                onChange={(e) => setIssueNumber(e.target.value)}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label
                htmlFor={`${formId}-issue-url`}
                className="block text-xs font-medium text-foreground mb-1"
              >
                Issue URL (optional)
              </label>
              <input
                id={`${formId}-issue-url`}
                type="url"
                placeholder="https://github.com/..."
                value={issueUrl}
                onChange={(e) => setIssueUrl(e.target.value)}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>
        )}

        {sourceType === 'BUG_FINDING' && (
          <div className="pt-2 border-t border-border/50">
            <label
              htmlFor={`${formId}-finding-id`}
              className="block text-xs font-medium text-foreground mb-1"
            >
              Bug Finding ID
            </label>
            <input
              id={`${formId}-finding-id`}
              type="text"
              placeholder="e.g. sec-finding-101"
              value={findingId}
              onChange={(e) => setFindingId(e.target.value)}
              className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        )}

        {/* Task Title */}
        <div>
          <label
            htmlFor={`${formId}-title`}
            className="block text-xs font-medium text-foreground mb-1"
          >
            Task Title <span className="text-destructive">*</span>
          </label>
          <input
            id={`${formId}-title`}
            type="text"
            placeholder="e.g. Fix Token Budget Overflow in AST Analyzer"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {clientErrors.title && (
            <p className="mt-1 text-xs text-destructive">{clientErrors.title}</p>
          )}
        </div>

        {/* Task Description */}
        <div>
          <label
            htmlFor={`${formId}-desc`}
            className="block text-xs font-medium text-foreground mb-1"
          >
            Description <span className="text-destructive">*</span>
          </label>
          <textarea
            id={`${formId}-desc`}
            rows={3}
            placeholder="Provide a detailed description of the goal, problem statement, or requested changes..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {clientErrors.description && (
            <p className="mt-1 text-xs text-destructive">{clientErrors.description}</p>
          )}
        </div>

        {/* Base Revision SHA */}
        <div>
          <label
            htmlFor={`${formId}-base-rev`}
            className="block text-xs font-medium text-foreground mb-1"
          >
            Base Commit SHA (optional)
          </label>
          <input
            id={`${formId}-base-rev`}
            type="text"
            placeholder="e.g. a1b2c3d4e5f6"
            value={baseRevision}
            onChange={(e) => setBaseRevision(e.target.value)}
            className="w-full py-2 px-3 text-sm font-mono bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 2: Segregated Requirements (min 1)                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
              <FileCode className="h-4 w-4 text-primary" />
              Requirements
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Specify segregated, verifiable functional goals and target file paths.
            </p>
          </div>
          <button
            type="button"
            onClick={addRequirement}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-foreground hover:bg-accent transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Requirement
          </button>
        </div>

        {clientErrors.requirements && (
          <p className="text-xs text-destructive">{clientErrors.requirements}</p>
        )}

        <div className="space-y-4">
          {requirements.map((req, idx) => (
            <div
              key={req.id || idx}
              className="p-4 rounded-md border border-border/80 bg-background/50 space-y-3"
            >
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="font-mono text-xs font-semibold text-primary">
                  {req.id || `req-${idx + 1}`}
                </span>
                {requirements.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeRequirement(idx)}
                    className="text-muted-foreground hover:text-destructive transition-colors p-1"
                    title="Remove requirement"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-[11px] font-medium text-foreground mb-1">
                    Requirement Description <span className="text-destructive">*</span>
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Cap AST symbol extraction depth to 4 levels"
                    value={req.description}
                    onChange={(e) => updateRequirement(idx, 'description', e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-foreground mb-1">
                    Category
                  </label>
                  <select
                    value={req.category}
                    onChange={(e) => updateRequirement(idx, 'category', e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {REQUIREMENT_CATEGORIES.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-foreground mb-1">
                    Target Files (comma-separated relative paths)
                  </label>
                  <input
                    type="text"
                    placeholder="src/analyzer/ast_walker.py, src/analyzer/budget.py"
                    value={req.targetFilesStr}
                    onChange={(e) => updateRequirement(idx, 'targetFilesStr', e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs font-mono bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-medium text-foreground mb-1">
                    Acceptance Criteria (comma-separated or lines)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Token count does not exceed limit"
                    value={req.acceptanceCriteriaStr}
                    onChange={(e) =>
                      updateRequirement(idx, 'acceptanceCriteriaStr', e.target.value)
                    }
                    className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 3: Assumptions (Dynamic)                                   */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-purple-400" />
              Assumptions (Optional)
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Identify architectural hypotheses, backward-compatibility assumptions, and unresolved questions.
            </p>
          </div>
          <button
            type="button"
            onClick={addAssumption}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-foreground hover:bg-accent transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Assumption
          </button>
        </div>

        {assumptions.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">No assumptions added yet.</p>
        ) : (
          <div className="space-y-3">
            {assumptions.map((asm, idx) => (
              <div
                key={asm.id || idx}
                className="p-3 rounded-md border border-border/80 bg-background/50 flex flex-col sm:flex-row items-stretch sm:items-center gap-3"
              >
                <div className="flex-1">
                  <input
                    type="text"
                    placeholder="e.g. Existing symbol table format remains backward-compatible"
                    value={asm.description}
                    onChange={(e) => updateAssumption(idx, 'description', e.target.value)}
                    className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <select
                    value={asm.risk_level}
                    onChange={(e) => updateAssumption(idx, 'risk_level', e.target.value)}
                    className="py-1.5 px-2 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none"
                  >
                    {RISK_LEVELS.map((rl) => (
                      <option key={rl} value={rl}>
                        {rl} risk
                      </option>
                    ))}
                  </select>

                  <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={asm.unresolved}
                      onChange={(e) => updateAssumption(idx, 'unresolved', e.target.checked)}
                      className="rounded border-border text-primary focus:ring-primary"
                    />
                    <span>Unresolved</span>
                  </label>

                  <button
                    type="button"
                    onClick={() => removeAssumption(idx)}
                    className="text-muted-foreground hover:text-destructive p-1"
                    title="Remove assumption"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 4: Constraints (Dynamic)                                   */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-400" />
              Constraints (Optional)
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Enforce security boundaries, protected files, forbidden dependencies, and token budgets.
            </p>
          </div>
          <button
            type="button"
            onClick={addConstraint}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md border border-border bg-background text-foreground hover:bg-accent transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Constraint
          </button>
        </div>

        {constraints.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">No constraints added yet.</p>
        ) : (
          <div className="space-y-4">
            {constraints.map((cst, idx) => (
              <div
                key={cst.id || idx}
                className="p-4 rounded-md border border-border/80 bg-background/50 space-y-3"
              >
                <div className="flex items-center justify-between border-b border-border/50 pb-2">
                  <span className="font-mono text-xs font-semibold text-amber-400">
                    {cst.id || `cst-${idx + 1}`}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeConstraint(idx)}
                    className="text-muted-foreground hover:text-destructive transition-colors p-1"
                    title="Remove constraint"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="sm:col-span-2">
                    <label className="block text-[11px] font-medium text-foreground mb-1">
                      Constraint Description
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Do not modify core parser grammar files"
                      value={cst.description}
                      onChange={(e) => updateConstraint(idx, 'description', e.target.value)}
                      className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-foreground mb-1">
                      Constraint Type
                    </label>
                    <select
                      value={cst.constraint_type}
                      onChange={(e) => updateConstraint(idx, 'constraint_type', e.target.value)}
                      className="w-full py-1.5 px-2.5 text-xs bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {CONSTRAINT_TYPES.map((ct) => (
                        <option key={ct} value={ct}>
                          {ct}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-foreground mb-1">
                      Forbidden Files (comma-separated)
                    </label>
                    <input
                      type="text"
                      placeholder="src/parser/grammar.py"
                      value={cst.forbiddenFilesStr}
                      onChange={(e) => updateConstraint(idx, 'forbiddenFilesStr', e.target.value)}
                      className="w-full py-1.5 px-2.5 text-xs font-mono bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-foreground mb-1">
                      Forbidden Packages (comma-separated)
                    </label>
                    <input
                      type="text"
                      placeholder="lodash, request"
                      value={cst.forbiddenPackagesStr}
                      onChange={(e) => updateConstraint(idx, 'forbiddenPackagesStr', e.target.value)}
                      className="w-full py-1.5 px-2.5 text-xs font-mono bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-foreground mb-1">
                      Max Budget Tokens
                    </label>
                    <input
                      type="number"
                      placeholder="e.g. 20000"
                      value={cst.maxBudgetTokensStr}
                      onChange={(e) => updateConstraint(idx, 'maxBudgetTokensStr', e.target.value)}
                      className="w-full py-1.5 px-2.5 text-xs font-mono bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Submit Action                                                      */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
        <button
          type="button"
          onClick={() => navigate('/app/tasks')}
          className="px-4 py-2 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          Cancel
        </button>

        <button
          type="submit"
          disabled={createTaskMutation.isPending}
          className="inline-flex items-center gap-2 px-5 py-2 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs disabled:opacity-50"
        >
          {createTaskMutation.isPending ? (
            <>
              <LoadingSpinner size="sm" label="Creating task..." />
              <span>Registering Task...</span>
            </>
          ) : (
            <>
              <span>Create Task</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </>
          )}
        </button>
      </div>
    </form>
  );
}
