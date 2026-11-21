/** Export buttons (Markdown + SARIF) for review and bug-detection results. */

import { Download } from 'lucide-react';
import {
  buildFindingsMarkdown,
  buildFindingsSarif,
  downloadTextFile,
  exportFileStem,
  type FindingsExportInput,
} from '../../lib/findingsExport';

const BUTTON =
  'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-border/70 text-[10px] font-mono text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors';

export function FindingsExportButtons({ input }: { input: FindingsExportInput }) {
  const stem = exportFileStem(input.kind, input.targetLabel);
  return (
    <div className="flex items-center gap-1.5" data-testid="findings-export-actions">
      <button
        type="button"
        className={BUTTON}
        title="Download a readable Markdown report"
        onClick={() => downloadTextFile(buildFindingsMarkdown(input), `${stem}.md`, 'text/markdown')}
      >
        <Download className="h-3 w-3" />
        Export .md
      </button>
      <button
        type="button"
        className={BUTTON}
        title="Download SARIF 2.1.0 for GitHub Code Scanning or IDE viewers"
        onClick={() => downloadTextFile(buildFindingsSarif(input), `${stem}.sarif`, 'application/sarif+json')}
      >
        <Download className="h-3 w-3" />
        Export SARIF
      </button>
    </div>
  );
}
