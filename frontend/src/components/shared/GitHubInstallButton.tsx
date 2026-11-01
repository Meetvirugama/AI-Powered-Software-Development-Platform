import { PlusCircle, ExternalLink } from 'lucide-react';
import { getGitHubAppInstallationUrl } from '../../lib/githubConfig';

interface GitHubInstallButtonProps {
  variant?: 'primary' | 'secondary';
  label?: string;
  size?: 'sm' | 'md';
  className?: string;
}

export function GitHubInstallButton({
  variant = 'primary',
  label = 'Install / Manage GitHub App',
  size = 'sm',
  className = '',
}: GitHubInstallButtonProps) {
  const installUrl = getGitHubAppInstallationUrl();

  const baseClasses =
    'inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  const sizeClasses =
    size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2.5 text-sm font-semibold';
  const variantClasses =
    variant === 'primary'
      ? 'bg-primary text-primary-foreground hover:bg-primary/90'
      : 'bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border';

  return (
    <a
      href={installUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      aria-label={label}
    >
      <PlusCircle className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} />
      <span>{label}</span>
      <ExternalLink className={size === 'sm' ? 'h-3 w-3 opacity-70' : 'h-3.5 w-3.5 opacity-70'} />
    </a>
  );
}

export default GitHubInstallButton;

