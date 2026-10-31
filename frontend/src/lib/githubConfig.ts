/**
 * GitHub App integration configuration and helper functions.
 */
export function getGitHubAppInstallationUrl(): string {
  const customUrl = import.meta.env.VITE_GITHUB_APP_INSTALLATION_URL;
  if (customUrl && typeof customUrl === 'string' && customUrl.trim()) {
    return customUrl.trim();
  }

  const appSlug = import.meta.env.VITE_GITHUB_APP_SLUG || 'ai-dev-platform-local';
  return `https://github.com/apps/${appSlug}/installations/new`;
}

